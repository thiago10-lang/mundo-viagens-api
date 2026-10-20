import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, jsonify, request
from sqlalchemy import or_

from modelos import Chamado, Cliente, Hotel, Reserva, Voo, agora, db
from provedores import CompanhiaIndisponivel
from regras import ErroNegocio, assentos_livres_agencia, confirmar_pagamento, registrar_log, so_digitos
from rotas_publicas import MENSAGEM_INDISPONIVEL, corpo, provedores_ativos
from seguranca import quem, requer

bp = Blueprint("equipe", __name__, url_prefix="/api/equipe")
EQUIPE = ("funcionario", "gerente")


@bp.get("/resumo")
@requer(*EQUIPE)
def resumo():
    momento = agora()
    inicio_dia = datetime.combine(momento.date(), datetime.min.time())
    inicio_mes = inicio_dia.replace(day=1)
    confirmadas_mes = Reserva.query.filter(Reserva.status == "confirmada", Reserva.pago_em >= inicio_mes).all()
    proximos = (
        Reserva.query.filter(Reserva.status == "confirmada", Reserva.partida > momento)
        .order_by(Reserva.partida)
        .limit(6)
        .all()
    )
    vendas_dias = []
    for deslocamento in range(6, -1, -1):
        dia = inicio_dia - timedelta(days=deslocamento)
        valor = (
            db.session.query(db.func.coalesce(db.func.sum(Reserva.total), 0))
            .filter(Reserva.pago.is_(True), Reserva.status == "confirmada", Reserva.pago_em >= dia, Reserva.pago_em < dia + timedelta(days=1))
            .scalar()
        )
        vendas_dias.append({"dia": dia.strftime("%d/%m"), "valor": float(valor)})
    return jsonify(
        pendentes=Reserva.query.filter_by(status="pendente").count(),
        vendas_hoje=Reserva.query.filter(Reserva.status == "confirmada", Reserva.pago_em >= inicio_dia).count(),
        receita_mes=round(sum(r.total for r in confirmadas_mes), 2),
        vendas_mes=len(confirmadas_mes),
        chamados_abertos=Chamado.query.filter_by(status="aberto").count(),
        clientes=Cliente.query.count(),
        bloqueados=Cliente.query.filter_by(bloqueado=True).count(),
        proximos_embarques=[r.dados(completo=False) for r in proximos],
        vendas_7_dias=vendas_dias,
    )


@bp.get("/reservas")
@requer(*EQUIPE)
def listar_reservas():
    consulta = Reserva.query.join(Cliente)
    status = request.args.get("status")
    if status:
        consulta = consulta.filter(Reserva.status == status)
    forma = request.args.get("forma")
    if forma:
        consulta = consulta.filter(Reserva.forma_pagamento == forma)
    busca = request.args.get("busca", "").strip()
    if busca:
        termo = f"%{busca}%"
        filtros = [Cliente.nome.ilike(termo), Reserva.codigo.ilike(termo), Reserva.localizador.ilike(termo), Reserva.destino.ilike(termo)]
        if so_digitos(busca):
            filtros.append(Cliente.cpf.like(f"%{so_digitos(busca)}%"))
        consulta = consulta.filter(or_(*filtros))
    reservas = consulta.order_by(Reserva.criado_em.desc()).limit(300).all()
    return jsonify([r.dados(completo=False) for r in reservas])


@bp.get("/reservas/<int:reserva_id>")
@requer(*EQUIPE)
def ver_reserva(reserva_id):
    reserva = db.session.get(Reserva, reserva_id)
    if not reserva:
        raise ErroNegocio("Reserva não encontrada.", 404)
    return jsonify(reserva.dados())


@bp.post("/reservas/<int:reserva_id>/confirmar-pagamento")
@requer(*EQUIPE)
def confirmar(reserva_id):
    reserva = db.session.get(Reserva, reserva_id)
    if not reserva or reserva.status != "pendente":
        raise ErroNegocio("Apenas reservas pendentes podem ter o pagamento confirmado.")
    provedor = provedores_ativos().get(reserva.provedor)
    if not provedor:
        raise ErroNegocio("A integração com esta companhia está desativada.", 503)
    try:
        confirmar_pagamento(reserva, provedor, quem())
    except CompanhiaIndisponivel:
        db.session.rollback()
        raise ErroNegocio(MENSAGEM_INDISPONIVEL, 503)
    db.session.commit()
    return jsonify(reserva.dados())


@bp.get("/clientes")
@requer(*EQUIPE)
def listar_clientes():
    consulta = Cliente.query
    busca = request.args.get("busca", "").strip()
    if busca:
        termo = f"%{busca}%"
        filtros = [Cliente.nome.ilike(termo), Cliente.email.ilike(termo)]
        if so_digitos(busca):
            filtros.append(Cliente.cpf.like(f"%{so_digitos(busca)}%"))
        consulta = consulta.filter(or_(*filtros))
    limite = agora() - timedelta(days=30)
    resultado = []
    for cliente in consulta.order_by(Cliente.nome).limit(300).all():
        dados = cliente.dados()
        reservas = Reserva.query.filter_by(cliente_id=cliente.id).all()
        dados["total_reservas"] = len(reservas)
        dados["total_gasto"] = round(sum(r.total for r in reservas if r.status == "confirmada"), 2)
        dados["cancelamentos_30_dias"] = sum(
            1 for r in reservas if r.status == "cancelada" and r.cancelado_em and r.cancelado_em >= limite
        )
        resultado.append(dados)
    return jsonify(resultado)


@bp.get("/clientes/<int:cliente_id>")
@requer(*EQUIPE)
def ver_cliente(cliente_id):
    cliente = db.session.get(Cliente, cliente_id)
    if not cliente:
        raise ErroNegocio("Cliente não encontrado.", 404)
    dados = cliente.dados()
    dados["reservas"] = [
        r.dados(completo=False) for r in Reserva.query.filter_by(cliente_id=cliente.id).order_by(Reserva.partida.desc())
    ]
    dados["chamados"] = [c.dados() for c in Chamado.query.filter_by(cliente_id=cliente.id).order_by(Chamado.id.desc())]
    return jsonify(dados)


@bp.get("/hoteis")
@requer(*EQUIPE)
def listar_hoteis():
    return jsonify([h.dados() for h in Hotel.query.order_by(Hotel.cidade, Hotel.nome).all()])


@bp.get("/chamados")
@requer(*EQUIPE)
def listar_chamados():
    consulta = Chamado.query
    status = request.args.get("status")
    if status:
        consulta = consulta.filter_by(status=status)
    return jsonify([c.dados() for c in consulta.order_by(Chamado.atualizado_em.desc()).limit(300).all()])


@bp.post("/chamados/<int:chamado_id>/status")
@requer(*EQUIPE)
def mudar_status_chamado(chamado_id):
    chamado = db.session.get(Chamado, chamado_id)
    novo = corpo().get("status")
    if not chamado or novo not in ("aberto", "respondido", "fechado"):
        raise ErroNegocio("Dados inválidos.")
    chamado.status = novo
    chamado.atualizado_em = agora()
    db.session.commit()
    return jsonify(chamado.dados(completo=True))


def periodo():
    hoje = date.today()
    try:
        inicio = date.fromisoformat(request.args.get("inicio", ""))
    except ValueError:
        inicio = (hoje.replace(day=1) - timedelta(days=330)).replace(day=1)
    try:
        fim = date.fromisoformat(request.args.get("fim", ""))
    except ValueError:
        fim = hoje
    return datetime.combine(inicio, datetime.min.time()), datetime.combine(fim + timedelta(days=1), datetime.min.time())


def reservas_do_periodo():
    inicio, fim = periodo()
    return Reserva.query.filter(Reserva.criado_em >= inicio, Reserva.criado_em < fim).all(), inicio, fim


@bp.get("/relatorios")
@requer(*EQUIPE)
def relatorios():
    reservas, inicio, fim = reservas_do_periodo()
    confirmadas = [r for r in reservas if r.status == "confirmada"]
    canceladas = [r for r in reservas if r.status == "cancelada"]
    pendentes = [r for r in reservas if r.status == "pendente"]
    receita = sum(r.total for r in confirmadas) + sum(r.multa for r in canceladas)
    mensal = defaultdict(lambda: {"vendas": 0, "receita": 0.0, "comissao": 0.0, "cancelamentos": 0})
    destinos = defaultdict(lambda: {"vendas": 0, "receita": 0.0})
    formas = defaultdict(lambda: {"quantidade": 0, "valor": 0.0})
    pacotes = defaultdict(int)
    clientes = defaultdict(lambda: {"compras": 0, "valor": 0.0})
    for r in reservas:
        mes = r.criado_em.strftime("%Y-%m")
        if r.status == "cancelada":
            mensal[mes]["cancelamentos"] += 1
            mensal[mes]["receita"] += r.multa
        if r.status == "confirmada":
            mensal[mes]["vendas"] += 1
            mensal[mes]["receita"] += r.total
            mensal[mes]["comissao"] += r.comissao
            destinos[r.destino]["vendas"] += 1
            destinos[r.destino]["receita"] += r.total
            formas[r.forma_pagamento]["quantidade"] += 1
            formas[r.forma_pagamento]["valor"] += r.total
            pacotes[(r.destino, r.hotel.nome if r.hotel else "Somente passagem aérea")] += 1
            clientes[r.cliente.nome]["compras"] += 1
            clientes[r.cliente.nome]["valor"] += r.total
    ocupacao = []
    for voo in Voo.query.filter(Voo.partida > agora()).order_by(Voo.partida).limit(15).all():
        vendidos = voo.assentos_total - assentos_livres_agencia(voo)
        ocupacao.append(
            {
                "codigo": voo.codigo,
                "rota": f"{voo.origem} → {voo.destino}",
                "partida": voo.partida.strftime("%Y-%m-%d %H:%M"),
                "vendidos": vendidos,
                "total": voo.assentos_total,
                "percentual": round(vendidos / voo.assentos_total * 100, 1) if voo.assentos_total else 0,
            }
        )

    def ordenar(dicionario, campo, chave_nome):
        return sorted(
            [{chave_nome: k, **{c: round(v, 2) if isinstance(v, float) else v for c, v in d.items()}} for k, d in dicionario.items()],
            key=lambda item: item[campo],
            reverse=True,
        )

    return jsonify(
        periodo={"inicio": inicio.date().isoformat(), "fim": (fim - timedelta(days=1)).date().isoformat()},
        resumo={
            "reservas": len(reservas),
            "confirmadas": len(confirmadas),
            "canceladas": len(canceladas),
            "pendentes": len(pendentes),
            "valor_pendente": round(sum(r.total for r in pendentes), 2),
            "receita": round(receita, 2),
            "comissao": round(sum(r.comissao for r in confirmadas), 2),
            "ticket_medio": round(sum(r.total for r in confirmadas) / len(confirmadas), 2) if confirmadas else 0,
            "taxa_cancelamento": round(len(canceladas) / len(reservas) * 100, 1) if reservas else 0,
            "multas": round(sum(r.multa for r in canceladas), 2),
        },
        mensal=sorted(
            [{"mes": k, **{c: round(v, 2) for c, v in d.items()}} for k, d in mensal.items()], key=lambda i: i["mes"]
        ),
        destinos=ordenar(destinos, "vendas", "destino")[:10],
        formas_pagamento=ordenar(formas, "valor", "forma"),
        pacotes=sorted(
            [{"destino": d, "pacote": p, "quantidade": q} for (d, p), q in pacotes.items()],
            key=lambda i: i["quantidade"],
            reverse=True,
        )[:10],
        melhores_clientes=ordenar(clientes, "valor", "cliente")[:10],
        ocupacao_voos=ocupacao,
    )


@bp.get("/relatorios/csv")
@requer(*EQUIPE)
def relatorio_csv():
    reservas, _, _ = reservas_do_periodo()
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";")
    escritor.writerow(
        ["Código", "Criada em", "Cliente", "CPF", "Origem", "Destino", "Partida", "Passageiros", "Hotel",
         "Forma", "Status", "Subtotal", "Descontos", "Comissão", "Total", "Multa", "Reembolso"]
    )
    for r in sorted(reservas, key=lambda x: x.criado_em):
        escritor.writerow(
            [
                r.codigo,
                r.criado_em.strftime("%d/%m/%Y %H:%M"),
                r.cliente.nome,
                r.cliente.cpf,
                r.origem,
                r.destino,
                r.partida.strftime("%d/%m/%Y %H:%M"),
                r.qtd_passageiros,
                r.hotel.nome if r.hotel else "",
                r.forma_pagamento,
                r.status,
                f"{r.subtotal:.2f}".replace(".", ","),
                f"{r.desconto_promocao + r.desconto_cupom + r.desconto_pontos:.2f}".replace(".", ","),
                f"{r.comissao:.2f}".replace(".", ","),
                f"{r.total:.2f}".replace(".", ","),
                f"{r.multa:.2f}".replace(".", ","),
                f"{r.reembolso:.2f}".replace(".", ","),
            ]
        )
    registrar_log(quem(), "relatorio_exportado", f"{len(reservas)} reservas")
    db.session.commit()
    return Response(
        "﻿" + saida.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=relatorio-mundo-viagens.csv"},
    )
