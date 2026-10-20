from datetime import date, datetime

from flask import Blueprint, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from modelos import Cliente, Funcionario, Hotel, Promocao, Voo, agora, db
from provedores import CIDADES, FORMATO, CompanhiaIndisponivel, com_retentativa
from regras import (
    ErroNegocio,
    assentos_livres_agencia,
    cpf_valido,
    cupom_valido,
    email_valido,
    ler_config,
    promocao_para,
    quartos_disponiveis,
    registrar_log,
    so_digitos,
)
from seguranca import carregar_usuario, gerar_token

bp = Blueprint("publico", __name__, url_prefix="/api")

MENSAGEM_INDISPONIVEL = (
    "O sistema da companhia aérea está temporariamente indisponível. "
    "Tentamos novamente automaticamente, mas não houve resposta. Tente de novo em alguns minutos."
)


def corpo():
    return request.get_json(silent=True) or {}


def provedores_ativos():
    from provedores import obter_provedores

    return obter_provedores(ler_config("skyhigh_ativo") == "1", ler_config("skyhigh_fora_do_ar") == "1")


def config_publica():
    return {
        chave: float(ler_config(chave))
        for chave in (
            "comissao",
            "multa_percentual",
            "prazo_cancelamento_horas",
            "valor_ponto",
            "pontos_por_real",
            "limite_desconto_pontos",
            "limite_cancelamentos",
            "janela_cancelamentos_dias",
        )
    }


@bp.get("/saude")
def saude():
    return jsonify(status="ok", horario=agora().strftime(FORMATO))


@bp.get("/cidades")
def cidades():
    return jsonify(CIDADES)


@bp.get("/inicio")
def inicio():
    hoje = date.today()
    promocoes = [
        p.dados()
        for p in Promocao.query.filter_by(ativa=True).order_by(Promocao.desconto.desc()).all()
        if not p.validade or p.validade >= hoje
    ]
    ofertas = []
    for voo in Voo.query.filter(Voo.ativo.is_(True), Voo.partida > agora()).order_by(Voo.preco).limit(30):
        livres = assentos_livres_agencia(voo)
        if livres > 0:
            dados = voo.dados()
            dados["assentos"] = livres
            ofertas.append(dados)
        if len(ofertas) == 6:
            break
    return jsonify(promocoes=promocoes, ofertas=ofertas, config=config_publica())


@bp.get("/voos")
def buscar_voos():
    origem = request.args.get("origem", "")
    destino = request.args.get("destino", "")
    data = request.args.get("data", "")
    try:
        passageiros = int(request.args.get("passageiros", 1))
        data_ok = date.fromisoformat(data) >= date.today()
    except ValueError:
        passageiros, data_ok = 0, False
    if origem not in CIDADES or destino not in CIDADES or origem == destino:
        raise ErroNegocio("Escolha uma origem e um destino diferentes.")
    if not data_ok or not 1 <= passageiros <= 9:
        raise ErroNegocio("Informe uma data a partir de hoje e de 1 a 9 passageiros.")
    resultados = []
    indisponiveis = []
    for provedor in provedores_ativos().values():
        try:
            resultados += com_retentativa(
                provedor.buscar, origem, destino, data, passageiros, tentativas=2, intervalo=0.5
            )
        except CompanhiaIndisponivel:
            indisponiveis.append(provedor.nome)
    momento = agora()
    resultados = [
        voo
        for voo in resultados
        if voo["assentos"] >= passageiros and datetime.strptime(voo["partida"], FORMATO) > momento
    ]
    resultados.sort(key=lambda voo: voo["preco"])
    promocao = promocao_para(destino)
    return jsonify(
        voos=resultados,
        indisponiveis=indisponiveis,
        aviso=MENSAGEM_INDISPONIVEL if indisponiveis else None,
        promocao=promocao.dados() if promocao else None,
    )


@bp.get("/hoteis")
def hoteis():
    cidade = request.args.get("cidade")
    consulta = Hotel.query.filter_by(ativo=True)
    if cidade:
        consulta = consulta.filter_by(cidade=cidade)
    try:
        checkin = date.fromisoformat(request.args.get("checkin", ""))
        checkout = date.fromisoformat(request.args.get("checkout", ""))
    except ValueError:
        checkin = checkout = None
    resultado = []
    for hotel in consulta.order_by(Hotel.cidade, Hotel.nome).all():
        dados = hotel.dados()
        if checkin and checkout and checkout > checkin:
            dados["disponiveis"] = quartos_disponiveis(hotel, checkin, checkout)
        resultado.append(dados)
    return jsonify(resultado)


@bp.post("/cupons/validar")
def validar_cupom():
    cupom = cupom_valido(corpo().get("codigo", ""))
    if not cupom:
        raise ErroNegocio("Informe um cupom.")
    return jsonify(codigo=cupom.codigo, desconto=cupom.desconto)


@bp.post("/auth/cadastro")
def cadastro():
    dados = corpo()
    nome = " ".join(str(dados.get("nome", "")).split())
    cpf = so_digitos(dados.get("cpf"))
    email = str(dados.get("email", "")).strip().lower()
    senha = str(dados.get("senha", ""))
    erros = []
    if len(nome.split()) < 2:
        erros.append("Informe seu nome completo.")
    if not cpf_valido(cpf):
        erros.append("CPF inválido.")
    elif Cliente.query.filter_by(cpf=cpf).first():
        erros.append("Este CPF já está cadastrado.")
    if not email_valido(email):
        erros.append("E-mail inválido.")
    elif Cliente.query.filter_by(email=email).first() or Funcionario.query.filter_by(email=email).first():
        erros.append("Este e-mail já está cadastrado.")
    if len(senha) < 6:
        erros.append("A senha deve ter pelo menos 6 caracteres.")
    if erros:
        raise ErroNegocio(" ".join(erros))
    cliente = Cliente(
        nome=nome,
        cpf=cpf,
        email=email,
        telefone=so_digitos(dados.get("telefone")) or None,
        senha_hash=generate_password_hash(senha),
    )
    db.session.add(cliente)
    registrar_log(f"cliente:{email}", "cadastro", f"Novo cliente {nome}")
    db.session.commit()
    return jsonify(token=gerar_token("cliente", cliente.id), usuario=cliente.dados()), 201


@bp.post("/auth/login")
def login():
    dados = corpo()
    email = str(dados.get("email", "")).strip().lower()
    senha = str(dados.get("senha", ""))
    funcionario = Funcionario.query.filter_by(email=email).first()
    if funcionario and funcionario.ativo and check_password_hash(funcionario.senha_hash, senha):
        registrar_log(f"{funcionario.perfil}:{email}", "login", "Acesso ao painel")
        db.session.commit()
        return jsonify(token=gerar_token(funcionario.perfil, funcionario.id), usuario=funcionario.dados())
    cliente = Cliente.query.filter_by(email=email).first()
    if cliente and check_password_hash(cliente.senha_hash, senha):
        return jsonify(token=gerar_token("cliente", cliente.id), usuario=cliente.dados())
    raise ErroNegocio("E-mail ou senha incorretos.", 401)


@bp.get("/auth/eu")
def eu():
    usuario, perfil = carregar_usuario()
    if not usuario:
        return jsonify(erro="Sessão expirada."), 401
    return jsonify(usuario.dados())
