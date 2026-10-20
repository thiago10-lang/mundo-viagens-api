# Mundo Viagens · API

Backend do sistema de vendas de pacotes de viagem da agência Mundo Viagens. API REST em Flask com banco PostgreSQL, separada do frontend.

- Frontend: https://github.com/thiago10-lang/mundo-viagens
- API em produção: https://mundo-viagens-api.onrender.com/api/saude

## Tecnologias
Python 3, Flask, SQLAlchemy, PostgreSQL (SQLite em desenvolvimento), JWT, Gunicorn, hospedagem no Render.

## Perfis e permissões
| Perfil | O que pode fazer |
|---|---|
| Cliente | Cadastrar-se, pesquisar voos, comprar passagens e pacotes com hotel, pagar com cartão, Pix ou boleto, usar cupons e pontos, fazer check-in com escolha de assento, emitir bilhete com QR Code, cancelar reservas, abrir chamados e receber notificações |
| Funcionário | Consultar reservas e clientes, confirmar pagamentos por boleto (emitindo os bilhetes), responder chamados, emitir relatórios e exportar CSV |
| Gerente | Tudo do funcionário, mais: bloquear/desbloquear clientes, criar viagens (voos do catálogo, inclusive em série), gerenciar hotéis, promoções e cupons, configurar valores (comissão, multa, prazos, pontos), adicionar/remover funcionários e consultar a auditoria |

## Regras de negócio
- RN1: cadastro obrigatório com nome completo, CPF válido e e-mail único.
- RN2: pacote só com passagem ou com hotel, verificando quartos livres por data.
- RN3: cartão e Pix confirmam na hora; boleto fica pendente até um funcionário confirmar.
- RN4: cancelamento grátis até o prazo configurado (48h); depois, multa configurável (20%). O cancelamento é enviado à companhia aérea.
- RN5: controle de quartos por data, sem overbooking; controle de assentos por voo.
- RN6: bloqueio automático após 3 cancelamentos em 30 dias; o gerente pode desbloquear.

## Integração com companhias aéreas
Os provedores de voo implementam a mesma interface (`ProvedorVoos`): o catálogo próprio da agência e a SkyHigh Airlines (simulador enquanto a API real não é liberada, ou cliente HTTPS real via `SKYHIGH_URL` e `SKYHIGH_CHAVE`). Falhas são tratadas com novas tentativas automáticas e mensagem amigável. Para adicionar outra companhia, basta criar uma nova classe e registrá-la em `obter_provedores()`.

## Executar localmente
```
pip install -r requirements.txt
python app.py
```
A API sobe em http://127.0.0.1:5000. Se o repositório do frontend estiver na pasta vizinha `mundo_viagens`, a interface também é servida nesse endereço.

## Variáveis de ambiente
| Variável | Uso |
|---|---|
| `DATABASE_URL` | Conexão PostgreSQL (sem ela, usa SQLite local) |
| `CHAVE_SECRETA` | Chave de assinatura dos tokens JWT |
| `FRONTEND_URL` | Origens liberadas no CORS (padrão: todas) |
| `SKYHIGH_URL` / `SKYHIGH_CHAVE` | API real da SkyHigh (opcional) |

## Contas de demonstração
| Perfil | E-mail | Senha |
|---|---|---|
| Cliente | cliente@teste.com | cliente123 |
| Funcionário | funcionario@mundoviagens.com | funcionario123 |
| Gerente | gerente@mundoviagens.com | gerente123 |
