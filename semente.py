import random
import string
from datetime import datetime, timedelta

from werkzeug.security import generate_password_hash

from modelos import Cliente, Cupom, Funcionario, Hotel, Passageiro, Promocao, Reserva, Voo, agora, db
from regras import PADROES, salvar_config

ROTAS = [
    ("São Paulo", "Rio de Janeiro", 65, 389.90, 8),
    ("Rio de Janeiro", "São Paulo", 65, 379.90, 18),
    ("São Paulo", "Salvador", 140, 689.90, 9),
    ("São Paulo", "Recife", 190, 749.90, 7),
    ("São Paulo", "Florianópolis", 70, 419.90, 11),
    ("Brasília", "Fortaleza", 170, 699.90, 10),
    ("Belo Horizonte", "Porto Alegre", 120, 559.90, 13),
    ("São Paulo", "Lisboa", 620, 3890.00, 21),
    ("São Paulo", "Buenos Aires", 175, 1490.00, 15),
    ("Rio de Janeiro", "Orlando", 560, 3590.00, 22),
]

CLIENTES_DEMO = [
    ("João da Silva", "52998224725", "cliente@teste.com", "cliente123"),
    ("Mariana Costa", "39053344705", "mariana@teste.com", "cliente123"),
    ("Pedro Almeida", "11144477735", "pedro@teste.com", "cliente123"),
    ("Luiza Fernandes", "15350946056", "luiza@teste.com", "cliente123"),
]


def codigo_aleatorio(gerador, prefixo, tamanho):
    return prefixo + "".join(gerador.choices(string.ascii_uppercase + string.digits, k=tamanho))


def popular():
    gerador = random.Random(42)
    db.session.add_all(
        [
            Funcionario(nome="Carlos Lima", email="gerente@mundoviagens.com", perfil="gerente", senha_hash=generate_password_hash("gerente123")),
            Funcionario(nome="Ana Pereira", email="funcionario@mundoviagens.com", perfil="funcionario", senha_hash=generate_password_hash("funcionario123")),
        ]
    )
    clientes = [
        Cliente(nome=n, cpf=c, email=e, senha_hash=generate_password_hash(s), criado_em=agora() - timedelta(days=200))
        for n, c, e, s in CLIENTES_DEMO
    ]
    db.session.add_all(clientes)
    hoteis = [
        Hotel(nome="Copacabana Mar Hotel", cidade="Rio de Janeiro", endereco="Av. Atlântica, 1500", estrelas=4, quartos=5, diaria=420),
        Hotel(nome="Rio Centro Inn", cidade="Rio de Janeiro", endereco="Rua da Carioca, 80", estrelas=3, quartos=8, diaria=260),
        Hotel(nome="Pelourinho Palace", cidade="Salvador", endereco="Largo do Pelourinho, 12", estrelas=4, quartos=4, diaria=310),
        Hotel(nome="Boa Viagem Resort", cidade="Recife", endereco="Av. Boa Viagem, 3000", estrelas=5, quartos=6, diaria=350),
        Hotel(nome="Iracema Praia Hotel", cidade="Fortaleza", endereco="Av. Beira Mar, 2200", estrelas=4, quartos=6, diaria=290),
        Hotel(nome="Floripa Beach Hotel", cidade="Florianópolis", endereco="Av. Beira-Mar Norte, 900", estrelas=4, quartos=5, diaria=380),
        Hotel(nome="Moinhos Suites", cidade="Porto Alegre", endereco="Rua Padre Chagas, 300", estrelas=4, quartos=6, diaria=330),
        Hotel(nome="Alfama Boutique", cidade="Lisboa", endereco="Rua de São Miguel, 25", estrelas=4, quartos=3, diaria=780),
        Hotel(nome="Le Petit Montmartre", cidade="Paris", endereco="Rue Lepic, 40", estrelas=3, quartos=3, diaria=1150),
        Hotel(nome="Orlando Parks Suites", cidade="Orlando", endereco="International Dr, 7000", estrelas=4, quartos=10, diaria=690),
        Hotel(nome="Palermo Soho Hotel", cidade="Buenos Aires", endereco="Honduras, 4800", estrelas=4, quartos=5, diaria=450),
    ]
    db.session.add_all(hoteis)
    db.session.add_all(
        [
            Promocao(destino="Salvador", descricao="Primavera na Bahia", desconto=15),
            Promocao(destino="Lisboa", descricao="Europa em alta", desconto=10),
            Promocao(destino="Florianópolis", descricao="Verão antecipado na Ilha", desconto=12),
            Cupom(codigo="BEMVINDO10", desconto=10, usos_max=1000),
            Cupom(codigo="FERIAS5", desconto=5),
        ]
    )
    for chave, valor in PADROES.items():
        salvar_config(chave, valor)
    hoje = agora().replace(hour=0, minute=0, second=0)
    numero_voo = 1000
    for origem, destino, duracao, preco, hora in ROTAS:
        numero_voo += 10
        for dia in range(1, 46):
            partida = hoje + timedelta(days=dia, hours=hora, minutes=gerador.choice([0, 15, 30, 45]))
            variacao = 1 + gerador.uniform(-0.15, 0.25)
            db.session.add(
                Voo(
                    codigo=f"MV{numero_voo}",
                    companhia="SkyHigh Airlines",
                    origem=origem,
                    destino=destino,
                    partida=partida,
                    chegada=partida + timedelta(minutes=duracao),
                    preco=round(preco * variacao, 2),
                    assentos_total=gerador.choice([120, 150, 180]),
                )
            )
    db.session.flush()
    for indice in range(60):
        cliente = gerador.choice(clientes)
        origem, destino, duracao, preco, hora = gerador.choice(ROTAS)
        criado = agora() - timedelta(days=gerador.randint(3, 300), hours=gerador.randint(0, 12))
        partida = criado + timedelta(days=gerador.randint(5, 40), hours=hora)
        pax = gerador.choice([1, 1, 2, 2, 3])
        hotel = next((h for h in hoteis if h.cidade == destino), None) if gerador.random() < 0.5 else None
        noites = gerador.randint(2, 6)
        preco_hotel = round(hotel.diaria * noites, 2) if hotel else 0
        subtotal = round(preco * pax + preco_hotel, 2)
        comissao = round(subtotal * 0.10, 2)
        total = round(subtotal + comissao, 2)
        forma = gerador.choice(["cartao", "cartao", "pix", "boleto"])
        status = gerador.choices(["confirmada", "cancelada", "pendente"], weights=[78, 15, 7])[0]
        if status == "pendente" and partida < agora():
            status = "confirmada"
        cancelada = status == "cancelada"
        multa = round(total * 0.2, 2) if cancelada and gerador.random() < 0.4 else 0
        reserva = Reserva(
            codigo=codigo_aleatorio(gerador, "MV", 6),
            cliente=cliente,
            provedor="skyhigh",
            voo_ref=f"SH{gerador.randint(1000, 9999)}|historico|{origem}|{destino}",
            voo_codigo=f"SH{gerador.randint(1000, 9999)}",
            companhia="SkyHigh Airlines",
            origem=origem,
            destino=destino,
            partida=partida,
            chegada=partida + timedelta(minutes=duracao),
            preco_voo=preco,
            qtd_passageiros=pax,
            hotel=hotel,
            checkin=partida.date() if hotel else None,
            checkout=(partida + timedelta(days=noites)).date() if hotel else None,
            quartos=1 if hotel else 0,
            preco_hotel=preco_hotel,
            subtotal=subtotal,
            comissao=comissao,
            total=total,
            forma_pagamento=forma,
            status=status,
            pago=status != "pendente",
            localizador=codigo_aleatorio(gerador, "", 6),
            pontos_ganhos=int(total) if status == "confirmada" else 0,
            multa=multa,
            reembolso=round(total - multa, 2) if cancelada else 0,
            confirmado_por="sistema" if status != "pendente" else None,
            criado_em=criado,
            pago_em=criado if status != "pendente" else None,
            cancelado_em=criado + timedelta(days=2) if cancelada else None,
        )
        reserva.passageiros = [
            Passageiro(nome=cliente.nome if p == 0 else f"Acompanhante {p} {cliente.nome.split()[-1]}", cpf=cliente.cpf if p == 0 else f"{gerador.randint(10**10, 10**11 - 1)}",
                       bilhete=None if status == "pendente" else "957-" + "".join(gerador.choices(string.digits, k=10)))
            for p in range(pax)
        ]
        if status == "confirmada":
            cliente.pontos += reserva.pontos_ganhos
        db.session.add(reserva)
    db.session.commit()


def inicializar():
    db.create_all()
    if not Funcionario.query.first():
        popular()
