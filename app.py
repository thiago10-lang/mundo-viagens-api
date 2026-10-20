import os

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

import rotas_cliente
import rotas_equipe
import rotas_gerente
import rotas_publicas
from modelos import db
from provedores import CompanhiaIndisponivel
from regras import ErroNegocio
from rotas_publicas import MENSAGEM_INDISPONIVEL
from semente import inicializar


def url_banco():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "mundo_viagens.db")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def criar_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = url_banco()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.json.ensure_ascii = False
    origens = os.environ.get("FRONTEND_URL", "*")
    CORS(app, resources={r"/api/*": {"origins": origens.split(",") if origens != "*" else "*"}})
    db.init_app(app)
    for modulo in (rotas_publicas, rotas_cliente, rotas_equipe, rotas_gerente):
        app.register_blueprint(modulo.bp)

    @app.errorhandler(ErroNegocio)
    def erro_negocio(erro):
        db.session.rollback()
        return jsonify(erro=erro.mensagem), erro.status

    @app.errorhandler(CompanhiaIndisponivel)
    def companhia_fora(erro):
        db.session.rollback()
        return jsonify(erro=MENSAGEM_INDISPONIVEL), 503

    @app.errorhandler(HTTPException)
    def erro_http(erro):
        return jsonify(erro=erro.description), erro.code

    @app.errorhandler(Exception)
    def erro_geral(erro):
        db.session.rollback()
        app.logger.exception(erro)
        return jsonify(erro="Erro interno. Tente novamente em instantes."), 500

    pasta_frontend = os.environ.get("PASTA_FRONTEND", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mundo_viagens"))
    if os.path.isfile(os.path.join(pasta_frontend, "index.html")):

        @app.get("/")
        @app.get("/<path:caminho>")
        def frontend(caminho="index.html"):
            if not os.path.isfile(os.path.join(pasta_frontend, caminho)):
                caminho = "index.html"
            return send_from_directory(pasta_frontend, caminho)

    else:

        @app.get("/")
        def raiz():
            return jsonify(api="Mundo Viagens", status="ok", documentacao="/api/saude")

    with app.app_context():
        inicializar()
        db.engine.dispose()
    return app


app = criar_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
