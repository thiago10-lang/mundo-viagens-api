import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

from modelos import Cliente, Funcionario, db

CHAVE = os.environ.get("CHAVE_SECRETA", "chave-local-de-desenvolvimento-mundo-viagens")
NIVEIS = {"cliente": 0, "funcionario": 1, "gerente": 2}


def gerar_token(perfil, usuario_id):
    expira = datetime.now(timezone.utc) + timedelta(hours=12)
    return jwt.encode({"sub": str(usuario_id), "perfil": perfil, "exp": expira}, CHAVE, algorithm="HS256")


def carregar_usuario():
    cabecalho = request.headers.get("Authorization", "")
    if not cabecalho.startswith("Bearer "):
        return None, None
    try:
        dados = jwt.decode(cabecalho[7:], CHAVE, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None, None
    perfil = dados.get("perfil")
    if perfil == "cliente":
        usuario = db.session.get(Cliente, int(dados["sub"]))
    else:
        usuario = db.session.get(Funcionario, int(dados["sub"]))
        if usuario and (not usuario.ativo or usuario.perfil != perfil):
            usuario = None
    return (usuario, perfil) if usuario else (None, None)


def requer(*perfis):
    def decorador(funcao):
        @wraps(funcao)
        def interna(*args, **kwargs):
            usuario, perfil = carregar_usuario()
            if not usuario:
                return jsonify(erro="Sessão expirada. Faça login novamente."), 401
            if perfil not in perfis:
                return jsonify(erro="Seu perfil não tem permissão para esta ação."), 403
            g.usuario = usuario
            g.perfil = perfil
            return funcao(*args, **kwargs)

        return interna

    return decorador


def quem():
    return f"{g.perfil}:{g.usuario.email}"
