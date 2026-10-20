import re
from datetime import date, timedelta

from modelos import (
    Cliente,
    Configuracao,
    Cupom,
    Hotel,
    Log,
    Notificacao,
    Passageiro,
    Promocao,
    Reserva,
    agora,
    db,
)

PADROES = {
    "comissao": "10",
    "multa_percentual": "20",
    "prazo_cancelamento_horas": "48",
    "limite_cancelamentos": "3",
    "janela_cancelamentos_dias": "30",
    "pontos_por_real": "1",
    "valor_ponto": "0.05",
    "limite_desconto_pontos": "30",
    "skyhigh_ativo": "1",
    "skyhigh_fora_do_ar": "0",
}

LETRAS_ASSENTO = "ABCDEF"


class ErroNegocio(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


def ler_config(chave):
    item = db.session.get(Configuracao, chave)
    return item.valor if item else PADROES.get(chave)


def config_numero(chave):
    return float(ler_config(chave))


def todas_configs():
    return {chave: ler_config(chave) for chave in PADROES}


def salvar_config(chave, valor):
    item = db.session.get(Configuracao, chave)
    if item:
        item.valor = str(valor)
    else:
        db.session.add(Configuracao(chave=chave, valor=str(valor)))


def registrar_log(usuario, acao, detalhe=""):
    db.session.add(Log(usuario=usuario, acao=acao, detalhe=detalhe[:500]))


def notificar(cliente_id, titulo, mensagem):
    db.session.add(Notificacao(cliente_id=cliente_id, titulo=titulo, mensagem=mensagem[:500]))


def so_digitos(texto):
    return re.sub(r"\D", "", texto or "")


def cpf_valido(cpf):
    numeros = so_digitos(cpf)
    if len(numeros) != 11 or numeros == numeros[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(numeros[i]) * (tamanho + 1 - i) for i in range(tamanho))
        if (soma * 10 % 11) % 10 != int(numeros[tamanho]):
            return False
    return True


def email_valido(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""))


def moeda(valor):
    texto = f"{valor or 0:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def reservas_ativas_do_voo(provedor, voo_ref):
    return Reserva.query.filter(
        Reserva.provedor == provedor, Reserva.voo_ref == str(voo_ref), Reserva.status != "cancelada"
    )


def assentos_livres_agencia(voo):
    vendidos = sum(r.qtd_passageiros for r in reservas_ativas_do_voo("agencia", voo.id))
    return max(voo.assentos_total - vendidos, 0)


def assentos_ocupados(provedor, voo_ref, ignorar_reserva=None):
    consulta = (
        db.session.query(Passageiro.assento)
        .join(Reserva)
        .filter(
            Reserva.provedor == provedor,
            Reserva.voo_ref == str(voo_ref),
            Reserva.status != "cancelada",
            Passageiro.assento.isnot(None),
        )
    )
    if ignorar_reserva:
        consulta = consulta.filter(Reserva.id != ignorar_reserva)
    return {linha[0] for linha in consulta.all()}


def quartos_disponiveis(hotel, checkin, checkout):
    ocupacoes = Reserva.query.filter(
        Reserva.hotel_id == hotel.id,
        Reserva.status != "cancelada",
        Reserva.checkin < checkout,
        Reserva.checkout > checkin,
    ).all()
    menor = hotel.quartos
    dia = checkin
    while dia < checkout:
        ocupados = sum(o.quartos for o in ocupacoes if o.checkin <= dia < o.checkout)
        menor = min(menor, hotel.quartos - ocupados)
        dia += timedelta(days=1)
    return max(menor, 0)


def promocao_para(destino):
    hoje = date.today()
    promocoes = Promocao.query.filter_by(destino=destino, ativa=True).order_by(Promocao.desconto.desc()).all()
    for promocao in promocoes:
        if not promocao.validade or promocao.validade >= hoje:
            return promocao
    return None


def cupom_valido(codigo):
    if not codigo:
        return None
    cupom = Cupom.query.filter(db.func.upper(Cupom.codigo) == codigo.strip().upper()).first()
    if not cupom or not cupom.ativo:
        raise ErroNegocio("Cupom inválido ou inativo.")
    if cupom.validade and cupom.validade < date.today():
        raise ErroNegocio("Este cupom expirou.")
    if cupom.usos_max is not None and cupom.usos >= cupom.usos_max:
        raise ErroNegocio("Este cupom atingiu o limite de usos.")
    return cupom


def calcular_valores(preco_voos, preco_hotel, promocao, cupom, pontos_solicitados, saldo_pontos):
    subtotal = round(preco_voos + preco_hotel, 2)
    desconto_promocao = round(subtotal * promocao.desconto / 100, 2) if promocao else 0
    base = subtotal - desconto_promocao
    desconto_cupom = round(base * cupom.desconto / 100, 2) if cupom else 0
    base -= desconto_cupom
    valor_ponto = config_numero("valor_ponto")
    limite = base * config_numero("limite_desconto_pontos") / 100
    pontos = max(0, min(int(pontos_solicitados or 0), saldo_pontos, int(limite / valor_ponto) if valor_ponto else 0))
    desconto_pontos = round(pontos * valor_ponto, 2)
    base -= desconto_pontos
    comissao = round(base * config_numero("comissao") / 100, 2)
    return {
        "subtotal": subtotal,
        "desconto_promocao": desconto_promocao,
        "desconto_cupom": desconto_cupom,
        "pontos_usados": pontos,
        "desconto_pontos": desconto_pontos,
        "comissao": comissao,
        "total": round(base + comissao, 2),
    }


def confirmar_pagamento(reserva, provedor, responsavel):
    from provedores import com_retentativa

    for passageiro in reserva.passageiros:
        if not passageiro.bilhete:
            passageiro.bilhete = com_retentativa(provedor.emitir_bilhete, reserva.localizador)
    reserva.status = "confirmada"
    reserva.pago = True
    reserva.pago_em = agora()
    reserva.confirmado_por = responsavel
    pontos = int(reserva.total * config_numero("pontos_por_real"))
    reserva.pontos_ganhos = pontos
    reserva.cliente.pontos += pontos
    notificar(
        reserva.cliente_id,
        "Reserva confirmada",
        f"Pagamento da reserva {reserva.codigo} aprovado. Bilhete emitido e {pontos} pontos creditados.",
    )
    registrar_log(responsavel, "pagamento_confirmado", f"Reserva {reserva.codigo} ({reserva.forma_pagamento}) {moeda(reserva.total)}")


def simular_cancelamento(reserva):
    horas = (reserva.partida - agora()).total_seconds() / 3600
    prazo = config_numero("prazo_cancelamento_horas")
    multa = round(reserva.total * config_numero("multa_percentual") / 100, 2) if reserva.pago and horas < prazo else 0
    reembolso = round(reserva.total - multa, 2) if reserva.pago else 0
    return {"horas_para_voo": round(horas, 1), "prazo_horas": prazo, "multa": multa, "reembolso": reembolso}


def verificar_bloqueio(cliente):
    if cliente.bloqueado:
        return False
    limite = agora() - timedelta(days=config_numero("janela_cancelamentos_dias"))
    if cliente.desbloqueado_em and cliente.desbloqueado_em > limite:
        limite = cliente.desbloqueado_em
    quantidade = Reserva.query.filter(
        Reserva.cliente_id == cliente.id, Reserva.status == "cancelada", Reserva.cancelado_em >= limite
    ).count()
    if quantidade >= config_numero("limite_cancelamentos"):
        cliente.bloqueado = True
        notificar(cliente.id, "Conta bloqueada", "Sua conta foi bloqueada para novas reservas por excesso de cancelamentos. Fale com a agência.")
        registrar_log("sistema", "bloqueio_automatico", f"Cliente {cliente.email} com {quantidade} cancelamentos")
        return True
    return False


def mapa_assentos(fileiras, ocupados):
    return [
        [{"assento": f"{fileira}{letra}", "ocupado": f"{fileira}{letra}" in ocupados} for letra in LETRAS_ASSENTO]
        for fileira in range(1, fileiras + 1)
    ]


def hotel_ativo(hotel_id, cidade):
    hotel = db.session.get(Hotel, int(hotel_id)) if str(hotel_id).isdigit() else None
    if not hotel or not hotel.ativo or hotel.cidade != cidade:
        raise ErroNegocio("Hotel inválido para este destino.")
    return hotel


def cliente_por_id(cliente_id):
    return db.session.get(Cliente, cliente_id)
