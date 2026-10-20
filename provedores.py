import json
import math
import os
import random
import string
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

CIDADES = [
    "São Paulo",
    "Rio de Janeiro",
    "Brasília",
    "Belo Horizonte",
    "Salvador",
    "Recife",
    "Fortaleza",
    "Florianópolis",
    "Porto Alegre",
    "Manaus",
    "Buenos Aires",
    "Santiago",
    "Lisboa",
    "Paris",
    "Orlando",
]

INTERNACIONAIS = {"Buenos Aires", "Santiago", "Lisboa", "Paris", "Orlando"}
FORMATO = "%Y-%m-%d %H:%M"


class CompanhiaIndisponivel(Exception):
    pass


class ProvedorVoos:
    chave = ""
    nome = ""

    def buscar(self, origem, destino, data, passageiros):
        raise NotImplementedError

    def obter(self, referencia):
        raise NotImplementedError

    def reservar(self, voo, passageiros, titular):
        raise NotImplementedError

    def emitir_bilhete(self, localizador):
        raise NotImplementedError

    def cancelar(self, localizador):
        raise NotImplementedError


def gerar_codigo(tamanho, alfabeto=string.ascii_uppercase + string.digits):
    return "".join(random.choices(alfabeto, k=tamanho))


class CatalogoAgencia(ProvedorVoos):
    chave = "agencia"
    nome = "Catálogo Mundo Viagens"

    def _formatar(self, voo):
        from regras import assentos_livres_agencia

        dados = voo.dados()
        dados.update(
            {
                "ref": f"{self.chave}:{voo.id}",
                "provedor": self.chave,
                "assentos": assentos_livres_agencia(voo),
                "fileiras": math.ceil(voo.assentos_total / 6),
            }
        )
        return dados

    def buscar(self, origem, destino, data, passageiros):
        from modelos import Voo

        inicio = datetime.strptime(data, "%Y-%m-%d")
        voos = Voo.query.filter(
            Voo.ativo.is_(True),
            Voo.origem == origem,
            Voo.destino == destino,
            Voo.partida >= inicio,
            Voo.partida < inicio + timedelta(days=1),
        ).all()
        return [self._formatar(voo) for voo in voos]

    def obter(self, referencia):
        from modelos import Voo, db

        voo = db.session.get(Voo, int(referencia)) if str(referencia).isdigit() else None
        return self._formatar(voo) if voo and voo.ativo else None

    def reservar(self, voo, passageiros, titular):
        return gerar_codigo(6)

    def emitir_bilhete(self, localizador):
        return "957-" + gerar_codigo(10, string.digits)

    def cancelar(self, localizador):
        return None


class SkyHighSimulada(ProvedorVoos):
    chave = "skyhigh"
    nome = "SkyHigh Airlines"

    def __init__(self, fora_do_ar=False):
        self.fora_do_ar = fora_do_ar

    def _verificar(self):
        if self.fora_do_ar:
            raise CompanhiaIndisponivel("SkyHigh fora do ar")

    def buscar(self, origem, destino, data, passageiros):
        self._verificar()
        gerador = random.Random(f"{origem}|{destino}|{data}")
        dia = datetime.strptime(data, "%Y-%m-%d")
        internacional = origem in INTERNACIONAIS or destino in INTERNACIONAIS
        voos = []
        for _ in range(gerador.randint(2, 5)):
            partida = dia + timedelta(hours=gerador.randint(5, 22), minutes=gerador.choice([0, 15, 30, 45]))
            duracao = gerador.randint(420, 720) if internacional else gerador.randint(60, 210)
            preco = gerador.uniform(1900, 5200) if internacional else gerador.uniform(250, 1400)
            codigo = f"SH{gerador.randint(1000, 9999)}"
            texto_partida = partida.strftime(FORMATO)
            voos.append(
                {
                    "ref": f"{self.chave}:{codigo}|{texto_partida}|{origem}|{destino}",
                    "provedor": self.chave,
                    "codigo": codigo,
                    "companhia": "SkyHigh Airlines",
                    "origem": origem,
                    "destino": destino,
                    "partida": texto_partida,
                    "chegada": (partida + timedelta(minutes=duracao)).strftime(FORMATO),
                    "preco": round(preco, 2),
                    "assentos": gerador.randint(0, 40),
                    "fileiras": 30,
                }
            )
        return sorted(voos, key=lambda voo: voo["partida"])

    def obter(self, referencia):
        partes = str(referencia).split("|")
        if len(partes) != 4:
            return None
        codigo, partida, origem, destino = partes
        try:
            datetime.strptime(partida, FORMATO)
        except ValueError:
            return None
        for voo in self.buscar(origem, destino, partida[:10], 1):
            if voo["codigo"] == codigo and voo["partida"] == partida:
                return voo
        return None

    def reservar(self, voo, passageiros, titular):
        self._verificar()
        return gerar_codigo(6)

    def emitir_bilhete(self, localizador):
        self._verificar()
        return "957-" + gerar_codigo(10, string.digits)

    def cancelar(self, localizador):
        self._verificar()


class SkyHighAPI(ProvedorVoos):
    chave = "skyhigh"
    nome = "SkyHigh Airlines"

    def __init__(self, url_base, chave_api, timeout=4):
        if not url_base.lower().startswith("https://"):
            raise ValueError("A API da SkyHigh deve ser acessada via HTTPS.")
        self.url_base = url_base.rstrip("/")
        self.chave_api = chave_api
        self.timeout = timeout

    def _chamar(self, metodo, caminho, dados=None):
        corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
        requisicao = urllib.request.Request(
            self.url_base + caminho,
            data=corpo,
            method=metodo,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.chave_api},
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=self.timeout) as resposta:
                conteudo = resposta.read().decode("utf-8")
                return json.loads(conteudo) if conteudo else {}
        except Exception as erro:
            raise CompanhiaIndisponivel(str(erro)) from erro

    def _formatar(self, voo):
        referencia = f"{self.chave}:{voo['codigo']}|{voo['partida']}|{voo['origem']}|{voo['destino']}"
        voo.update({"provedor": self.chave, "ref": referencia, "fileiras": 30})
        return voo

    def buscar(self, origem, destino, data, passageiros):
        parametros = urllib.parse.urlencode(
            {"origem": origem, "destino": destino, "data": data, "passageiros": passageiros}
        )
        return [self._formatar(v) for v in self._chamar("GET", "/voos?" + parametros).get("voos", [])]

    def obter(self, referencia):
        codigo, partida = str(referencia).split("|")[:2]
        parametros = urllib.parse.urlencode({"codigo": codigo, "partida": partida})
        voo = self._chamar("GET", "/voos/detalhe?" + parametros)
        return self._formatar(voo) if voo else None

    def reservar(self, voo, passageiros, titular):
        dados = {"voo": voo["codigo"], "partida": voo["partida"], "passageiros": passageiros, "titular": titular}
        return self._chamar("POST", "/reservas", dados)["localizador"]

    def emitir_bilhete(self, localizador):
        return self._chamar("POST", f"/reservas/{localizador}/bilhete", {})["bilhete"]

    def cancelar(self, localizador):
        self._chamar("DELETE", f"/reservas/{localizador}")


def com_retentativa(funcao, *argumentos, tentativas=3, intervalo=1.0):
    for tentativa in range(1, tentativas + 1):
        try:
            return funcao(*argumentos)
        except CompanhiaIndisponivel:
            if tentativa == tentativas:
                raise
            time.sleep(intervalo)


def obter_provedores(skyhigh_ativo=True, simular_falha=False):
    provedores = {CatalogoAgencia.chave: CatalogoAgencia()}
    if skyhigh_ativo:
        url = os.environ.get("SKYHIGH_URL")
        provedores["skyhigh"] = (
            SkyHighAPI(url, os.environ.get("SKYHIGH_CHAVE", "")) if url else SkyHighSimulada(simular_falha)
        )
    return provedores
