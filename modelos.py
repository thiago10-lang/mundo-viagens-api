from datetime import datetime
from zoneinfo import ZoneInfo

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
FUSO = ZoneInfo("America/Sao_Paulo")


def agora():
    return datetime.now(FUSO).replace(tzinfo=None, microsecond=0)


def fmt(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d %H:%M")
    return valor.isoformat()


class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(11), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telefone = db.Column(db.String(20))
    senha_hash = db.Column(db.String(255), nullable=False)
    bloqueado = db.Column(db.Boolean, default=False, nullable=False)
    desbloqueado_em = db.Column(db.DateTime)
    pontos = db.Column(db.Integer, default=0, nullable=False)
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)

    def nivel(self):
        if self.pontos >= 10000:
            return "Ouro"
        if self.pontos >= 2000:
            return "Prata"
        return "Bronze"

    def dados(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "cpf": self.cpf,
            "email": self.email,
            "telefone": self.telefone,
            "bloqueado": self.bloqueado,
            "pontos": self.pontos,
            "nivel": self.nivel(),
            "criado_em": fmt(self.criado_em),
            "perfil": "cliente",
        }


class Funcionario(db.Model):
    __tablename__ = "funcionarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    perfil = db.Column(db.String(20), nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "email": self.email,
            "perfil": self.perfil,
            "ativo": self.ativo,
            "criado_em": fmt(self.criado_em),
        }


class Voo(db.Model):
    __tablename__ = "voos"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(12), nullable=False)
    companhia = db.Column(db.String(60), nullable=False)
    origem = db.Column(db.String(60), nullable=False)
    destino = db.Column(db.String(60), nullable=False)
    partida = db.Column(db.DateTime, nullable=False)
    chegada = db.Column(db.DateTime, nullable=False)
    preco = db.Column(db.Float, nullable=False)
    assentos_total = db.Column(db.Integer, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "codigo": self.codigo,
            "companhia": self.companhia,
            "origem": self.origem,
            "destino": self.destino,
            "partida": fmt(self.partida),
            "chegada": fmt(self.chegada),
            "preco": self.preco,
            "assentos_total": self.assentos_total,
            "ativo": self.ativo,
        }


class Hotel(db.Model):
    __tablename__ = "hoteis"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cidade = db.Column(db.String(60), nullable=False)
    endereco = db.Column(db.String(200))
    estrelas = db.Column(db.Integer, default=3, nullable=False)
    quartos = db.Column(db.Integer, nullable=False)
    diaria = db.Column(db.Float, nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "cidade": self.cidade,
            "endereco": self.endereco,
            "estrelas": self.estrelas,
            "quartos": self.quartos,
            "diaria": self.diaria,
            "ativo": self.ativo,
        }


class Promocao(db.Model):
    __tablename__ = "promocoes"
    id = db.Column(db.Integer, primary_key=True)
    destino = db.Column(db.String(60), nullable=False)
    descricao = db.Column(db.String(120), nullable=False)
    desconto = db.Column(db.Float, nullable=False)
    validade = db.Column(db.Date)
    ativa = db.Column(db.Boolean, default=True, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "destino": self.destino,
            "descricao": self.descricao,
            "desconto": self.desconto,
            "validade": fmt(self.validade),
            "ativa": self.ativa,
        }


class Cupom(db.Model):
    __tablename__ = "cupons"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(30), unique=True, nullable=False)
    desconto = db.Column(db.Float, nullable=False)
    usos_max = db.Column(db.Integer)
    usos = db.Column(db.Integer, default=0, nullable=False)
    validade = db.Column(db.Date)
    ativo = db.Column(db.Boolean, default=True, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "codigo": self.codigo,
            "desconto": self.desconto,
            "usos_max": self.usos_max,
            "usos": self.usos,
            "validade": fmt(self.validade),
            "ativo": self.ativo,
        }


class Reserva(db.Model):
    __tablename__ = "reservas"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    provedor = db.Column(db.String(20), nullable=False)
    voo_ref = db.Column(db.String(60), nullable=False)
    voo_codigo = db.Column(db.String(12), nullable=False)
    companhia = db.Column(db.String(60), nullable=False)
    origem = db.Column(db.String(60), nullable=False)
    destino = db.Column(db.String(60), nullable=False)
    partida = db.Column(db.DateTime, nullable=False)
    chegada = db.Column(db.DateTime, nullable=False)
    preco_voo = db.Column(db.Float, nullable=False)
    qtd_passageiros = db.Column(db.Integer, nullable=False)
    hotel_id = db.Column(db.Integer, db.ForeignKey("hoteis.id"))
    checkin = db.Column(db.Date)
    checkout = db.Column(db.Date)
    quartos = db.Column(db.Integer, default=0, nullable=False)
    preco_hotel = db.Column(db.Float, default=0, nullable=False)
    subtotal = db.Column(db.Float, nullable=False)
    desconto_promocao = db.Column(db.Float, default=0, nullable=False)
    cupom_codigo = db.Column(db.String(30))
    desconto_cupom = db.Column(db.Float, default=0, nullable=False)
    pontos_usados = db.Column(db.Integer, default=0, nullable=False)
    desconto_pontos = db.Column(db.Float, default=0, nullable=False)
    comissao = db.Column(db.Float, default=0, nullable=False)
    total = db.Column(db.Float, nullable=False)
    forma_pagamento = db.Column(db.String(10), nullable=False)
    status = db.Column(db.String(12), nullable=False)
    pago = db.Column(db.Boolean, default=False, nullable=False)
    localizador = db.Column(db.String(12), nullable=False)
    checkin_feito = db.Column(db.Boolean, default=False, nullable=False)
    pontos_ganhos = db.Column(db.Integer, default=0, nullable=False)
    multa = db.Column(db.Float, default=0, nullable=False)
    reembolso = db.Column(db.Float, default=0, nullable=False)
    confirmado_por = db.Column(db.String(120))
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)
    pago_em = db.Column(db.DateTime)
    cancelado_em = db.Column(db.DateTime)

    cliente = db.relationship("Cliente")
    hotel = db.relationship("Hotel")
    passageiros = db.relationship(
        "Passageiro", backref="reserva", cascade="all, delete-orphan", order_by="Passageiro.id"
    )

    def dados(self, completo=True):
        resultado = {
            "id": self.id,
            "codigo": self.codigo,
            "cliente_id": self.cliente_id,
            "cliente_nome": self.cliente.nome if self.cliente else None,
            "provedor": self.provedor,
            "voo_codigo": self.voo_codigo,
            "companhia": self.companhia,
            "origem": self.origem,
            "destino": self.destino,
            "partida": fmt(self.partida),
            "chegada": fmt(self.chegada),
            "qtd_passageiros": self.qtd_passageiros,
            "hotel": self.hotel.nome if self.hotel else None,
            "total": self.total,
            "forma_pagamento": self.forma_pagamento,
            "status": self.status,
            "pago": self.pago,
            "localizador": self.localizador,
            "checkin_feito": self.checkin_feito,
            "criado_em": fmt(self.criado_em),
        }
        if completo:
            resultado.update(
                {
                    "cliente_email": self.cliente.email if self.cliente else None,
                    "cliente_cpf": self.cliente.cpf if self.cliente else None,
                    "preco_voo": self.preco_voo,
                    "hotel_id": self.hotel_id,
                    "hotel_endereco": self.hotel.endereco if self.hotel else None,
                    "checkin": fmt(self.checkin),
                    "checkout": fmt(self.checkout),
                    "quartos": self.quartos,
                    "preco_hotel": self.preco_hotel,
                    "subtotal": self.subtotal,
                    "desconto_promocao": self.desconto_promocao,
                    "cupom_codigo": self.cupom_codigo,
                    "desconto_cupom": self.desconto_cupom,
                    "pontos_usados": self.pontos_usados,
                    "desconto_pontos": self.desconto_pontos,
                    "comissao": self.comissao,
                    "pontos_ganhos": self.pontos_ganhos,
                    "multa": self.multa,
                    "reembolso": self.reembolso,
                    "confirmado_por": self.confirmado_por,
                    "pago_em": fmt(self.pago_em),
                    "cancelado_em": fmt(self.cancelado_em),
                    "passageiros": [p.dados() for p in self.passageiros],
                }
            )
        return resultado


class Passageiro(db.Model):
    __tablename__ = "passageiros"
    id = db.Column(db.Integer, primary_key=True)
    reserva_id = db.Column(db.Integer, db.ForeignKey("reservas.id"), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    cpf = db.Column(db.String(11), nullable=False)
    nascimento = db.Column(db.Date)
    assento = db.Column(db.String(4))
    bilhete = db.Column(db.String(20))

    def dados(self):
        return {
            "id": self.id,
            "nome": self.nome,
            "cpf": self.cpf,
            "nascimento": fmt(self.nascimento),
            "assento": self.assento,
            "bilhete": self.bilhete,
        }


class Notificacao(db.Model):
    __tablename__ = "notificacoes"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    titulo = db.Column(db.String(120), nullable=False)
    mensagem = db.Column(db.String(500), nullable=False)
    lida = db.Column(db.Boolean, default=False, nullable=False)
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "titulo": self.titulo,
            "mensagem": self.mensagem,
            "lida": self.lida,
            "criado_em": fmt(self.criado_em),
        }


class Chamado(db.Model):
    __tablename__ = "chamados"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    reserva_id = db.Column(db.Integer, db.ForeignKey("reservas.id"))
    assunto = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(12), default="aberto", nullable=False)
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)
    atualizado_em = db.Column(db.DateTime, default=agora, nullable=False)

    cliente = db.relationship("Cliente")
    reserva = db.relationship("Reserva")
    mensagens = db.relationship(
        "MensagemChamado", backref="chamado", cascade="all, delete-orphan", order_by="MensagemChamado.id"
    )

    def dados(self, completo=False):
        resultado = {
            "id": self.id,
            "assunto": self.assunto,
            "status": self.status,
            "cliente_nome": self.cliente.nome if self.cliente else None,
            "reserva_codigo": self.reserva.codigo if self.reserva else None,
            "reserva_id": self.reserva_id,
            "criado_em": fmt(self.criado_em),
            "atualizado_em": fmt(self.atualizado_em),
        }
        if completo:
            resultado["mensagens"] = [m.dados() for m in self.mensagens]
        return resultado


class MensagemChamado(db.Model):
    __tablename__ = "mensagens_chamado"
    id = db.Column(db.Integer, primary_key=True)
    chamado_id = db.Column(db.Integer, db.ForeignKey("chamados.id"), nullable=False)
    autor = db.Column(db.String(120), nullable=False)
    da_equipe = db.Column(db.Boolean, default=False, nullable=False)
    texto = db.Column(db.Text, nullable=False)
    criado_em = db.Column(db.DateTime, default=agora, nullable=False)

    def dados(self):
        return {
            "id": self.id,
            "autor": self.autor,
            "da_equipe": self.da_equipe,
            "texto": self.texto,
            "criado_em": fmt(self.criado_em),
        }


class Configuracao(db.Model):
    __tablename__ = "configuracoes"
    chave = db.Column(db.String(40), primary_key=True)
    valor = db.Column(db.String(100), nullable=False)


class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    data_hora = db.Column(db.DateTime, default=agora, nullable=False)
    usuario = db.Column(db.String(150), nullable=False)
    acao = db.Column(db.String(60), nullable=False)
    detalhe = db.Column(db.String(500))

    def dados(self):
        return {
            "id": self.id,
            "data_hora": fmt(self.data_hora),
            "usuario": self.usuario,
            "acao": self.acao,
            "detalhe": self.detalhe,
        }
