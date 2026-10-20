import math
import random
import string
from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify
from werkzeug.security import check_password_hash, generate_password_hash

from modelos import Chamado, MensagemChamado, Notificacao, Passageiro, Reserva, Voo, agora, db
from provedores import FORMATO, CompanhiaIndisponivel, com_retentativa
from regras import (
    ErroNegocio,
    LETRAS_ASSENTO,
    assentos_ocupados,
    calcular_valores,
    confirmar_pagamento,
    cpf_valido,
    cupom_valido,
    hotel_ativo,
    ler_config,
    mapa_assentos,
    moeda,
    notificar,
    promocao_para,
    quartos_disponiveis,
    registrar_log,
    simular_cancelamento,
    so_digitos,
    verificar_bloqueio,
)
from rotas_publicas import MENSAGEM_INDISPONIVEL, corpo, provedores_ativos
from seguranca import quem, requer

bp = Blueprint("cliente", __name__, url_prefix="/api")


def novo_codigo():
    while True:
        codigo = "MV" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Reserva.query.filter_by(codigo=codigo).first():
            return codigo


def dias_uteis(inicio, quantidade):
    dia = inicio
    while quantidade > 0:
        dia += timedelta(days=1)
        if dia.weekday() < 5:
            quantidade -= 1
    return dia


def reserva_do_cliente(reserva_id):
    reserva = db.session.get(Reserva, reserva_id)
    if not reserva or reserva.cliente_id != g.usuario.id:
        raise ErroNegocio("Reserva não encontrada.", 404)
    return reserva


def detalhes_reserva(reserva):
    dados = reserva.dados()
    if reserva.status == "pendente" and reserva.forma_pagamento == "boleto":
        dados["boleto"] = {
            "linha": f"23793.38128 60{reserva.id:06d}.{reserva.localizador} 4 {int(reserva.total * 100):014d}",
            "vencimento": dias_uteis(reserva.criado_em.date(), 2).isoformat(),
        }
    if reserva.status != "cancelada" and reserva.partida > agora():
        dados["simulacao_cancelamento"] = simular_cancelamento(reserva)
    dados["pode_checkin"] = reserva.status == "confirmada" and reserva.partida - agora() > timedelta(hours=1)
    return dados


def validar_passageiros(lista):
    if not isinstance(lista, list) or not 1 <= len(lista) <= 9:
        raise ErroNegocio("Informe de 1 a 9 passageiros.")
    passageiros = []
    cpfs = set()
    for indice, item in enumerate(lista, start=1):
        nome = " ".join(str(item.get("nome", "")).split())
        cpf = so_digitos(item.get("cpf"))
        if len(nome.split()) < 2:
            raise ErroNegocio(f"Passageiro {indice}: informe nome e sobrenome como no documento.")
        if not cpf_valido(cpf):
            raise ErroNegocio(f"Passageiro {indice}: CPF inválido.")
        if cpf in cpfs:
            raise ErroNegocio(f"Passageiro {indice}: CPF repetido na mesma reserva.")
        cpfs.add(cpf)
        nascimento = None
        if item.get("nascimento"):
            try:
                nascimento = date.fromisoformat(item["nascimento"])
            except ValueError:
                raise ErroNegocio(f"Passageiro {indice}: data de nascimento inválida.")
            if nascimento >= date.today():
                raise ErroNegocio(f"Passageiro {indice}: data de nascimento inválida.")
        passageiros.append(Passageiro(nome=nome, cpf=cpf, nascimento=nascimento))
    return passageiros


def validar_pagamento(forma, cartao):
    if forma == "cartao":
        numero = so_digitos(cartao.get("numero"))
        validade = str(cartao.get("validade", ""))
        if not 13 <= len(numero) <= 19:
            raise ErroNegocio("Número do cartão inválido.")
        if not str(cartao.get("nome", "")).strip():
            raise ErroNegocio("Informe o nome impresso no cartão.")
        try:
            mes, ano = validade.split("/")
            vencimento = date(2000 + int(ano), int(mes), 1)
        except ValueError:
            raise ErroNegocio("Validade do cartão deve estar no formato MM/AA.")
        if vencimento < date.today().replace(day=1):
            raise ErroNegocio("Cartão vencido.")
        if not so_digitos(cartao.get("cvv")) or len(so_digitos(cartao.get("cvv"))) not in (3, 4):
            raise ErroNegocio("CVV inválido.")
    elif forma not in ("pix", "boleto"):
        raise ErroNegocio("Escolha a forma de pagamento.")


@bp.get("/me")
@requer("cliente")
def meu_perfil():
    dados = g.usuario.dados()
    dados["valor_pontos"] = round(g.usuario.pontos * float(ler_config("valor_ponto")), 2)
    dados["nao_lidas"] = Notificacao.query.filter_by(cliente_id=g.usuario.id, lida=False).count()
    return jsonify(dados)


@bp.put("/me")
@requer("cliente")
def atualizar_perfil():
    dados = corpo()
    cliente = g.usuario
    nome = " ".join(str(dados.get("nome", cliente.nome)).split())
    if len(nome.split()) < 2:
        raise ErroNegocio("Informe seu nome completo.")
    cliente.nome = nome
    cliente.telefone = so_digitos(dados.get("telefone")) or None
    if dados.get("nova_senha"):
        if not check_password_hash(cliente.senha_hash, str(dados.get("senha_atual", ""))):
            raise ErroNegocio("Senha atual incorreta.")
        if len(dados["nova_senha"]) < 6:
            raise ErroNegocio("A nova senha deve ter pelo menos 6 caracteres.")
        cliente.senha_hash = generate_password_hash(dados["nova_senha"])
    registrar_log(quem(), "perfil_atualizado", "Dados cadastrais alterados")
    db.session.commit()
    return jsonify(cliente.dados())


@bp.get("/me/reservas")
@requer("cliente")
def minhas_reservas():
    reservas = Reserva.query.filter_by(cliente_id=g.usuario.id).order_by(Reserva.partida.desc()).all()
    return jsonify([r.dados(completo=False) for r in reservas])


@bp.post("/reservas")
@requer("cliente")
def criar_reserva():
    cliente = g.usuario
    dados = corpo()
    if cliente.bloqueado:
        raise ErroNegocio("Sua conta está bloqueada para novas reservas. Entre em contato com a agência.", 403)
    chave, _, referencia = str(dados.get("voo", "")).partition(":")
    provedor = provedores_ativos().get(chave)
    if not provedor:
        raise ErroNegocio("Voo inválido.")
    voo = com_retentativa(provedor.obter, referencia)
    if not voo:
        raise ErroNegocio("Voo não encontrado. Faça uma nova busca.")
    partida = datetime.strptime(voo["partida"], FORMATO)
    if partida <= agora():
        raise ErroNegocio("Este voo já partiu.")
    passageiros = validar_passageiros(dados.get("passageiros"))
    if voo["assentos"] < len(passageiros):
        raise ErroNegocio(f"Restam apenas {voo['assentos']} assento(s) neste voo.")
    hotel, checkin, checkout, quartos, preco_hotel = None, None, None, 0, 0
    info_hotel = dados.get("hotel")
    if info_hotel:
        hotel = hotel_ativo(info_hotel.get("id"), voo["destino"])
        try:
            checkin = date.fromisoformat(str(info_hotel.get("checkin")))
            checkout = date.fromisoformat(str(info_hotel.get("checkout")))
            quartos = int(info_hotel.get("quartos", 1))
        except (ValueError, TypeError):
            raise ErroNegocio("Datas de hospedagem inválidas.")
        if checkout <= checkin or quartos < 1:
            raise ErroNegocio("O check-out deve ser depois do check-in e é preciso ao menos 1 quarto.")
        if checkin < partida.date():
            raise ErroNegocio("O check-in não pode ser antes da data do voo.")
        livres = quartos_disponiveis(hotel, checkin, checkout)
        if quartos > livres:
            raise ErroNegocio(f"O {hotel.nome} tem apenas {livres} quarto(s) livre(s) nessas datas.")
        preco_hotel = round(hotel.diaria * (checkout - checkin).days * quartos, 2)
    pagamento = dados.get("pagamento") or {}
    forma = pagamento.get("forma")
    validar_pagamento(forma, pagamento.get("cartao") or {})
    cupom = cupom_valido(dados.get("cupom"))
    valores = calcular_valores(
        voo["preco"] * len(passageiros),
        preco_hotel,
        promocao_para(voo["destino"]),
        cupom,
        dados.get("pontos"),
        cliente.pontos,
    )
    titular = {"nome": cliente.nome, "cpf": cliente.cpf, "email": cliente.email}
    try:
        localizador = com_retentativa(provedor.reservar, voo, len(passageiros), titular)
    except CompanhiaIndisponivel:
        raise ErroNegocio(MENSAGEM_INDISPONIVEL, 503)
    reserva = Reserva(
        codigo=novo_codigo(),
        cliente=cliente,
        provedor=chave,
        voo_ref=referencia,
        voo_codigo=voo["codigo"],
        companhia=voo["companhia"],
        origem=voo["origem"],
        destino=voo["destino"],
        partida=partida,
        chegada=datetime.strptime(voo["chegada"], FORMATO),
        preco_voo=voo["preco"],
        qtd_passageiros=len(passageiros),
        hotel=hotel,
        checkin=checkin,
        checkout=checkout,
        quartos=quartos,
        preco_hotel=preco_hotel,
        cupom_codigo=cupom.codigo if cupom else None,
        forma_pagamento=forma,
        status="pendente",
        localizador=localizador,
        passageiros=passageiros,
        **valores,
    )
    db.session.add(reserva)
    cliente.pontos -= valores["pontos_usados"]
    if cupom:
        cupom.usos += 1
    registrar_log(
        quem(),
        "reserva_criada",
        f"Reserva {reserva.codigo} {reserva.origem} -> {reserva.destino}, {len(passageiros)} pax, "
        f"{'com hotel' if hotel else 'somente aéreo'}, {moeda(reserva.total)} via {forma}",
    )
    if forma in ("cartao", "pix"):
        try:
            confirmar_pagamento(reserva, provedor, quem())
        except CompanhiaIndisponivel:
            db.session.rollback()
            try:
                provedor.cancelar(localizador)
            except CompanhiaIndisponivel:
                pass
            raise ErroNegocio(MENSAGEM_INDISPONIVEL, 503)
    else:
        notificar(
            cliente.id,
            "Reserva aguardando pagamento",
            f"Sua reserva {reserva.codigo} foi registrada. Pague o boleto em até 2 dias úteis para confirmar.",
        )
    db.session.commit()
    return jsonify(detalhes_reserva(reserva)), 201


@bp.get("/reservas/<int:reserva_id>")
@requer("cliente")
def ver_reserva(reserva_id):
    return jsonify(detalhes_reserva(reserva_do_cliente(reserva_id)))


@bp.post("/reservas/<int:reserva_id>/cancelar")
@requer("cliente")
def cancelar_reserva(reserva_id):
    reserva = reserva_do_cliente(reserva_id)
    if reserva.status == "cancelada":
        raise ErroNegocio("Esta reserva já está cancelada.")
    if reserva.partida <= agora():
        raise ErroNegocio("Não é possível cancelar uma reserva cujo voo já partiu.")
    simulacao = simular_cancelamento(reserva)
    provedor = provedores_ativos().get(reserva.provedor)
    if provedor:
        try:
            com_retentativa(provedor.cancelar, reserva.localizador)
        except CompanhiaIndisponivel:
            raise ErroNegocio(MENSAGEM_INDISPONIVEL, 503)
    cliente = reserva.cliente
    reserva.status = "cancelada"
    reserva.multa = simulacao["multa"]
    reserva.reembolso = simulacao["reembolso"]
    reserva.cancelado_em = agora()
    cliente.pontos = max(cliente.pontos - reserva.pontos_ganhos + reserva.pontos_usados, 0)
    notificar(
        cliente.id,
        "Reserva cancelada",
        f"A reserva {reserva.codigo} foi cancelada. Multa {moeda(reserva.multa)}, reembolso {moeda(reserva.reembolso)}.",
    )
    registrar_log(quem(), "reserva_cancelada", f"Reserva {reserva.codigo}, multa {moeda(reserva.multa)}, reembolso {moeda(reserva.reembolso)}")
    db.session.flush()
    bloqueado = verificar_bloqueio(cliente)
    db.session.commit()
    dados = detalhes_reserva(reserva)
    dados["cliente_bloqueado"] = bloqueado
    return jsonify(dados)


def fileiras_do_voo(reserva):
    if reserva.provedor == "agencia":
        voo = db.session.get(Voo, int(reserva.voo_ref))
        return math.ceil(voo.assentos_total / 6) if voo else 25
    return 30


@bp.get("/reservas/<int:reserva_id>/assentos")
@requer("cliente")
def assentos(reserva_id):
    reserva = reserva_do_cliente(reserva_id)
    if reserva.status != "confirmada":
        raise ErroNegocio("O check-in só fica disponível para reservas confirmadas.")
    ocupados = assentos_ocupados(reserva.provedor, reserva.voo_ref, ignorar_reserva=reserva.id)
    return jsonify(
        mapa=mapa_assentos(fileiras_do_voo(reserva), ocupados),
        passageiros=[p.dados() for p in reserva.passageiros],
        letras=LETRAS_ASSENTO,
    )


@bp.post("/reservas/<int:reserva_id>/checkin")
@requer("cliente")
def fazer_checkin(reserva_id):
    reserva = reserva_do_cliente(reserva_id)
    if reserva.status != "confirmada":
        raise ErroNegocio("O check-in só fica disponível para reservas confirmadas.")
    if reserva.partida - agora() <= timedelta(hours=1):
        raise ErroNegocio("O check-in online encerra 1 hora antes do voo.")
    escolhas = corpo().get("assentos") or {}
    fileiras = fileiras_do_voo(reserva)
    validos = {f"{f}{l}" for f in range(1, fileiras + 1) for l in LETRAS_ASSENTO}
    ocupados = assentos_ocupados(reserva.provedor, reserva.voo_ref, ignorar_reserva=reserva.id)
    usados = set()
    for passageiro in reserva.passageiros:
        assento = str(escolhas.get(str(passageiro.id), "")).upper()
        if assento not in validos:
            raise ErroNegocio(f"Escolha um assento válido para {passageiro.nome}.")
        if assento in ocupados or assento in usados:
            raise ErroNegocio(f"O assento {assento} já está ocupado.")
        usados.add(assento)
        passageiro.assento = assento
    reserva.checkin_feito = True
    notificar(reserva.cliente_id, "Check-in realizado", f"Check-in da reserva {reserva.codigo} concluído. Seu cartão de embarque já está disponível.")
    registrar_log(quem(), "checkin", f"Reserva {reserva.codigo} assentos {', '.join(sorted(usados))}")
    db.session.commit()
    return jsonify(detalhes_reserva(reserva))


@bp.get("/me/notificacoes")
@requer("cliente")
def notificacoes():
    itens = Notificacao.query.filter_by(cliente_id=g.usuario.id).order_by(Notificacao.id.desc()).limit(50).all()
    return jsonify([n.dados() for n in itens])


@bp.post("/me/notificacoes/lidas")
@requer("cliente")
def marcar_lidas():
    Notificacao.query.filter_by(cliente_id=g.usuario.id, lida=False).update({"lida": True})
    db.session.commit()
    return jsonify(ok=True)


@bp.get("/me/chamados")
@requer("cliente")
def meus_chamados():
    chamados = Chamado.query.filter_by(cliente_id=g.usuario.id).order_by(Chamado.atualizado_em.desc()).all()
    return jsonify([c.dados() for c in chamados])


@bp.post("/me/chamados")
@requer("cliente")
def abrir_chamado():
    dados = corpo()
    assunto = str(dados.get("assunto", "")).strip()
    texto = str(dados.get("mensagem", "")).strip()
    if not assunto or not texto:
        raise ErroNegocio("Informe o assunto e a mensagem.")
    reserva_id = dados.get("reserva_id")
    if reserva_id:
        reserva_do_cliente(int(reserva_id))
    chamado = Chamado(cliente_id=g.usuario.id, reserva_id=reserva_id or None, assunto=assunto[:150])
    chamado.mensagens.append(MensagemChamado(autor=g.usuario.nome, texto=texto))
    db.session.add(chamado)
    registrar_log(quem(), "chamado_aberto", assunto[:200])
    db.session.commit()
    return jsonify(chamado.dados(completo=True)), 201


def chamado_acessivel(chamado_id):
    chamado = db.session.get(Chamado, chamado_id)
    if not chamado or (g.perfil == "cliente" and chamado.cliente_id != g.usuario.id):
        raise ErroNegocio("Chamado não encontrado.", 404)
    return chamado


@bp.get("/chamados/<int:chamado_id>")
@requer("cliente", "funcionario", "gerente")
def ver_chamado(chamado_id):
    return jsonify(chamado_acessivel(chamado_id).dados(completo=True))


@bp.post("/chamados/<int:chamado_id>/mensagens")
@requer("cliente", "funcionario", "gerente")
def responder_chamado(chamado_id):
    chamado = chamado_acessivel(chamado_id)
    texto = str(corpo().get("texto", "")).strip()
    if not texto:
        raise ErroNegocio("Escreva uma mensagem.")
    if chamado.status == "fechado":
        raise ErroNegocio("Este chamado está encerrado.")
    da_equipe = g.perfil != "cliente"
    chamado.mensagens.append(MensagemChamado(autor=g.usuario.nome, texto=texto, da_equipe=da_equipe))
    chamado.status = "respondido" if da_equipe else "aberto"
    chamado.atualizado_em = agora()
    if da_equipe:
        notificar(chamado.cliente_id, "Resposta do atendimento", f"Respondemos seu chamado \"{chamado.assunto}\".")
    registrar_log(quem(), "chamado_mensagem", f"Chamado #{chamado.id}")
    db.session.commit()
    return jsonify(chamado.dados(completo=True))
