from datetime import date, datetime, timedelta

from flask import Blueprint, g, jsonify, request
from werkzeug.security import generate_password_hash

from modelos import Cliente, Cupom, Funcionario, Hotel, Log, Promocao, Reserva, Voo, agora, db
from provedores import CIDADES, FORMATO
from regras import (
    PADROES,
    ErroNegocio,
    assentos_livres_agencia,
    email_valido,
    notificar,
    registrar_log,
    salvar_config,
    todas_configs,
)
from rotas_publicas import corpo
from seguranca import quem, requer

bp = Blueprint("gerente", __name__, url_prefix="/api/gerente")

LIMITES_CONFIG = {
    "comissao": (0, 50),
    "multa_percentual": (0, 100),
    "prazo_cancelamento_horas": (0, 720),
    "limite_cancelamentos": (1, 50),
    "janela_cancelamentos_dias": (1, 365),
    "pontos_por_real": (0, 100),
    "valor_ponto": (0, 10),
    "limite_desconto_pontos": (0, 100),
    "skyhigh_ativo": (0, 1),
    "skyhigh_fora_do_ar": (0, 1),
}


def numero(valor, nome, minimo=None, maximo=None, inteiro=False):
    try:
        resultado = int(valor) if inteiro else float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        raise ErroNegocio(f"{nome} inválido.")
    if (minimo is not None and resultado < minimo) or (maximo is not None and resultado > maximo):
        raise ErroNegocio(f"{nome} deve estar entre {minimo} e {maximo}.")
    return resultado


def data_opcional(valor):
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErroNegocio("Data inválida.")


@bp.post("/clientes/<int:cliente_id>/bloqueio")
@requer("gerente")
def bloqueio(cliente_id):
    cliente = db.session.get(Cliente, cliente_id)
    if not cliente:
        raise ErroNegocio("Cliente não encontrado.", 404)
    bloquear = bool(corpo().get("bloquear"))
    cliente.bloqueado = bloquear
    if not bloquear:
        cliente.desbloqueado_em = agora()
        notificar(cliente.id, "Conta desbloqueada", "Sua conta foi liberada para novas reservas.")
    registrar_log(quem(), "cliente_bloqueado" if bloquear else "cliente_desbloqueado", cliente.email)
    db.session.commit()
    return jsonify(cliente.dados())


def dados_voo(voo):
    dados = voo.dados()
    livres = assentos_livres_agencia(voo)
    dados["vendidos"] = voo.assentos_total - livres
    dados["assentos"] = livres
    return dados


def ler_voo(dados):
    origem = dados.get("origem")
    destino = dados.get("destino")
    if origem not in CIDADES or destino not in CIDADES or origem == destino:
        raise ErroNegocio("Escolha origem e destino diferentes.")
    try:
        partida = datetime.strptime(str(dados.get("partida", "")).replace("T", " ")[:16], FORMATO)
    except ValueError:
        raise ErroNegocio("Data e hora de partida inválidas.")
    duracao = numero(dados.get("duracao_minutos"), "Duração", 20, 1440, inteiro=True)
    codigo = str(dados.get("codigo", "")).strip().upper()
    if not 3 <= len(codigo) <= 12:
        raise ErroNegocio("Informe o código do voo (ex.: MV1020).")
    return {
        "codigo": codigo,
        "companhia": str(dados.get("companhia") or "SkyHigh Airlines").strip()[:60],
        "origem": origem,
        "destino": destino,
        "partida": partida,
        "chegada": partida + timedelta(minutes=duracao),
        "preco": numero(dados.get("preco"), "Preço", 1, 100000),
        "assentos_total": numero(dados.get("assentos_total"), "Assentos", 6, 600, inteiro=True),
    }


@bp.get("/voos")
@requer("gerente")
def listar_voos():
    consulta = Voo.query
    if request.args.get("todos") != "1":
        consulta = consulta.filter(Voo.partida > agora() - timedelta(days=1))
    return jsonify([dados_voo(v) for v in consulta.order_by(Voo.partida).limit(500).all()])


@bp.post("/voos")
@requer("gerente")
def criar_voo():
    dados = corpo()
    base = ler_voo(dados)
    if base["partida"] <= agora():
        raise ErroNegocio("A partida precisa ser no futuro.")
    repeticoes = numero(dados.get("repetir_dias") or 1, "Quantidade de dias", 1, 60, inteiro=True)
    criados = []
    for dia in range(repeticoes):
        voo = Voo(**{**base, "partida": base["partida"] + timedelta(days=dia), "chegada": base["chegada"] + timedelta(days=dia)})
        db.session.add(voo)
        criados.append(voo)
    registrar_log(quem(), "voo_criado", f"{base['codigo']} {base['origem']} -> {base['destino']} ({repeticoes} data(s))")
    db.session.commit()
    return jsonify([dados_voo(v) for v in criados]), 201


@bp.put("/voos/<int:voo_id>")
@requer("gerente")
def editar_voo(voo_id):
    voo = db.session.get(Voo, voo_id)
    if not voo:
        raise ErroNegocio("Voo não encontrado.", 404)
    dados = corpo()
    novos = ler_voo(dados)
    vendidos = voo.assentos_total - assentos_livres_agencia(voo)
    if novos["assentos_total"] < vendidos:
        raise ErroNegocio(f"Já existem {vendidos} assentos vendidos neste voo.")
    if vendidos and (novos["origem"] != voo.origem or novos["destino"] != voo.destino):
        raise ErroNegocio("Não é possível mudar a rota de um voo com passagens vendidas.")
    for campo, valor in novos.items():
        setattr(voo, campo, valor)
    if "ativo" in dados:
        voo.ativo = bool(dados["ativo"])
    registrar_log(quem(), "voo_editado", f"Voo #{voo.id} {voo.codigo}")
    db.session.commit()
    return jsonify(dados_voo(voo))


@bp.delete("/voos/<int:voo_id>")
@requer("gerente")
def remover_voo(voo_id):
    voo = db.session.get(Voo, voo_id)
    if not voo:
        raise ErroNegocio("Voo não encontrado.", 404)
    possui_reservas = Reserva.query.filter_by(provedor="agencia", voo_ref=str(voo.id)).count() > 0
    if possui_reservas:
        voo.ativo = False
        mensagem = "O voo possui reservas e foi apenas desativado para novas vendas."
    else:
        db.session.delete(voo)
        mensagem = "Voo removido."
    registrar_log(quem(), "voo_removido", f"{voo.codigo} {voo.partida}")
    db.session.commit()
    return jsonify(mensagem=mensagem)


def ler_hotel(dados):
    nome = str(dados.get("nome", "")).strip()
    if not nome or dados.get("cidade") not in CIDADES:
        raise ErroNegocio("Informe nome e cidade do hotel.")
    return {
        "nome": nome[:120],
        "cidade": dados["cidade"],
        "endereco": str(dados.get("endereco", "")).strip()[:200],
        "estrelas": numero(dados.get("estrelas") or 3, "Estrelas", 1, 5, inteiro=True),
        "quartos": numero(dados.get("quartos"), "Quartos", 1, 5000, inteiro=True),
        "diaria": numero(dados.get("diaria"), "Diária", 1, 100000),
    }


@bp.get("/hoteis")
@requer("gerente")
def listar_hoteis():
    return jsonify([h.dados() for h in Hotel.query.order_by(Hotel.cidade, Hotel.nome).all()])


@bp.post("/hoteis")
@requer("gerente")
def criar_hotel():
    hotel = Hotel(**ler_hotel(corpo()))
    db.session.add(hotel)
    registrar_log(quem(), "hotel_criado", f"{hotel.nome} ({hotel.cidade})")
    db.session.commit()
    return jsonify(hotel.dados()), 201


@bp.put("/hoteis/<int:hotel_id>")
@requer("gerente")
def editar_hotel(hotel_id):
    hotel = db.session.get(Hotel, hotel_id)
    if not hotel:
        raise ErroNegocio("Hotel não encontrado.", 404)
    dados = corpo()
    if set(dados) == {"ativo"}:
        hotel.ativo = bool(dados["ativo"])
    else:
        for campo, valor in ler_hotel(dados).items():
            setattr(hotel, campo, valor)
        if "ativo" in dados:
            hotel.ativo = bool(dados["ativo"])
    registrar_log(quem(), "hotel_editado", f"Hotel #{hotel.id} {hotel.nome}")
    db.session.commit()
    return jsonify(hotel.dados())


@bp.get("/promocoes")
@requer("gerente")
def listar_promocoes():
    return jsonify(
        promocoes=[p.dados() for p in Promocao.query.order_by(Promocao.ativa.desc(), Promocao.destino).all()],
        cupons=[c.dados() for c in Cupom.query.order_by(Cupom.ativo.desc(), Cupom.codigo).all()],
    )


@bp.post("/promocoes")
@requer("gerente")
def criar_promocao():
    dados = corpo()
    descricao = str(dados.get("descricao", "")).strip()
    if dados.get("destino") not in CIDADES or not descricao:
        raise ErroNegocio("Informe destino e descrição.")
    promocao = Promocao(
        destino=dados["destino"],
        descricao=descricao[:120],
        desconto=numero(dados.get("desconto"), "Desconto", 1, 90),
        validade=data_opcional(dados.get("validade")),
    )
    db.session.add(promocao)
    registrar_log(quem(), "promocao_criada", f"{descricao}: {promocao.desconto}% para {promocao.destino}")
    db.session.commit()
    return jsonify(promocao.dados()), 201


@bp.put("/promocoes/<int:promocao_id>")
@requer("gerente")
def alternar_promocao(promocao_id):
    promocao = db.session.get(Promocao, promocao_id)
    if not promocao:
        raise ErroNegocio("Promoção não encontrada.", 404)
    promocao.ativa = bool(corpo().get("ativa"))
    registrar_log(quem(), "promocao_alterada", f"{promocao.descricao} ativa={promocao.ativa}")
    db.session.commit()
    return jsonify(promocao.dados())


@bp.delete("/promocoes/<int:promocao_id>")
@requer("gerente")
def remover_promocao(promocao_id):
    promocao = db.session.get(Promocao, promocao_id)
    if promocao:
        registrar_log(quem(), "promocao_removida", promocao.descricao)
        db.session.delete(promocao)
        db.session.commit()
    return jsonify(ok=True)


@bp.post("/cupons")
@requer("gerente")
def criar_cupom():
    dados = corpo()
    codigo = str(dados.get("codigo", "")).strip().upper()
    if not codigo.isalnum() or not 3 <= len(codigo) <= 30:
        raise ErroNegocio("O código do cupom deve ter de 3 a 30 letras ou números.")
    if Cupom.query.filter(db.func.upper(Cupom.codigo) == codigo).first():
        raise ErroNegocio("Já existe um cupom com este código.")
    usos_max = dados.get("usos_max")
    cupom = Cupom(
        codigo=codigo,
        desconto=numero(dados.get("desconto"), "Desconto", 1, 90),
        usos_max=numero(usos_max, "Limite de usos", 1, 1000000, inteiro=True) if usos_max not in (None, "") else None,
        validade=data_opcional(dados.get("validade")),
    )
    db.session.add(cupom)
    registrar_log(quem(), "cupom_criado", f"{codigo} {cupom.desconto}%")
    db.session.commit()
    return jsonify(cupom.dados()), 201


@bp.put("/cupons/<int:cupom_id>")
@requer("gerente")
def alternar_cupom(cupom_id):
    cupom = db.session.get(Cupom, cupom_id)
    if not cupom:
        raise ErroNegocio("Cupom não encontrado.", 404)
    cupom.ativo = bool(corpo().get("ativo"))
    registrar_log(quem(), "cupom_alterado", f"{cupom.codigo} ativo={cupom.ativo}")
    db.session.commit()
    return jsonify(cupom.dados())


@bp.delete("/cupons/<int:cupom_id>")
@requer("gerente")
def remover_cupom(cupom_id):
    cupom = db.session.get(Cupom, cupom_id)
    if cupom:
        registrar_log(quem(), "cupom_removido", cupom.codigo)
        db.session.delete(cupom)
        db.session.commit()
    return jsonify(ok=True)


@bp.get("/config")
@requer("gerente")
def ver_config():
    return jsonify(todas_configs())


@bp.put("/config")
@requer("gerente")
def alterar_config():
    dados = corpo()
    alteracoes = []
    for chave, valor in dados.items():
        if chave not in PADROES:
            continue
        minimo, maximo = LIMITES_CONFIG[chave]
        convertido = numero(valor, chave.replace("_", " ").capitalize(), minimo, maximo)
        texto = str(int(convertido)) if convertido == int(convertido) else str(convertido)
        salvar_config(chave, texto)
        alteracoes.append(f"{chave}={texto}")
    registrar_log(quem(), "configuracoes", ", ".join(alteracoes))
    db.session.commit()
    return jsonify(todas_configs())


@bp.get("/funcionarios")
@requer("gerente")
def listar_funcionarios():
    return jsonify([f.dados() for f in Funcionario.query.order_by(Funcionario.perfil.desc(), Funcionario.nome).all()])


@bp.post("/funcionarios")
@requer("gerente")
def criar_funcionario():
    dados = corpo()
    nome = " ".join(str(dados.get("nome", "")).split())
    email = str(dados.get("email", "")).strip().lower()
    senha = str(dados.get("senha", ""))
    perfil = dados.get("perfil")
    if len(nome.split()) < 2:
        raise ErroNegocio("Informe o nome completo.")
    if not email_valido(email):
        raise ErroNegocio("E-mail inválido.")
    if Funcionario.query.filter_by(email=email).first() or Cliente.query.filter_by(email=email).first():
        raise ErroNegocio("Este e-mail já está em uso.")
    if perfil not in ("funcionario", "gerente"):
        raise ErroNegocio("Perfil inválido.")
    if len(senha) < 6:
        raise ErroNegocio("A senha deve ter pelo menos 6 caracteres.")
    funcionario = Funcionario(nome=nome, email=email, perfil=perfil, senha_hash=generate_password_hash(senha))
    db.session.add(funcionario)
    registrar_log(quem(), "funcionario_criado", f"{email} ({perfil})")
    db.session.commit()
    return jsonify(funcionario.dados()), 201


@bp.put("/funcionarios/<int:funcionario_id>")
@requer("gerente")
def editar_funcionario(funcionario_id):
    funcionario = db.session.get(Funcionario, funcionario_id)
    if not funcionario:
        raise ErroNegocio("Funcionário não encontrado.", 404)
    dados = corpo()
    if funcionario.id == g.usuario.id and (dados.get("perfil", "gerente") != "gerente" or dados.get("ativo") is False):
        raise ErroNegocio("Você não pode rebaixar ou desativar a sua própria conta.")
    if "nome" in dados and len(str(dados["nome"]).split()) >= 2:
        funcionario.nome = " ".join(str(dados["nome"]).split())
    if dados.get("perfil") in ("funcionario", "gerente"):
        funcionario.perfil = dados["perfil"]
    if "ativo" in dados:
        funcionario.ativo = bool(dados["ativo"])
    if dados.get("senha"):
        if len(dados["senha"]) < 6:
            raise ErroNegocio("A senha deve ter pelo menos 6 caracteres.")
        funcionario.senha_hash = generate_password_hash(dados["senha"])
    registrar_log(quem(), "funcionario_editado", f"{funcionario.email} perfil={funcionario.perfil} ativo={funcionario.ativo}")
    db.session.commit()
    return jsonify(funcionario.dados())


@bp.delete("/funcionarios/<int:funcionario_id>")
@requer("gerente")
def remover_funcionario(funcionario_id):
    funcionario = db.session.get(Funcionario, funcionario_id)
    if not funcionario:
        raise ErroNegocio("Funcionário não encontrado.", 404)
    if funcionario.id == g.usuario.id:
        raise ErroNegocio("Você não pode remover a sua própria conta.")
    registrar_log(quem(), "funcionario_removido", funcionario.email)
    db.session.delete(funcionario)
    db.session.commit()
    return jsonify(ok=True)


@bp.get("/logs")
@requer("gerente")
def logs():
    consulta = Log.query
    busca = request.args.get("busca", "").strip()
    if busca:
        termo = f"%{busca}%"
        consulta = consulta.filter(db.or_(Log.usuario.ilike(termo), Log.acao.ilike(termo), Log.detalhe.ilike(termo)))
    return jsonify([l.dados() for l in consulta.order_by(Log.id.desc()).limit(400).all()])
