# Manual de uso — Sistema de Acompanhamento de Pagamentos de Celulares

Guia para quem usa o sistema no dia a dia (financeiro e dono). Explica **cada
página**, o que fazer em cada uma e as regras por trás dos números.

> Documentação técnica de instalação e deploy fica em `README.md`, `docs/DEPLOY.md`,
> `docs/WHATSAPP.md` e `docs/CORA.md`. Este manual é só de **operação**.

---

## Sumário

1. [Conceitos que aparecem em toda tela](#1-conceitos-que-aparecem-em-toda-tela)
2. [Entrar / Sair (`/entrar/`)](#2-entrar--sair)
3. [Barra de navegação](#3-barra-de-navegação)
4. [Início (`/`) — resumo do dia](#4-início--resumo-do-dia)
5. [Clientes — lista (`/clientes/`)](#5-clientes--lista)
6. [Clientes — novo / editar](#6-clientes--novo--editar)
7. [Clientes — ficha do cliente (`/clientes/<id>/`)](#7-clientes--ficha-do-cliente)
8. [Contratos — lista (`/contratos/`)](#8-contratos--lista)
9. [Contratos — novo / editar](#9-contratos--novo--editar)
10. [Contratos — detalhe do contrato (`/contratos/<id>/`)](#10-contratos--detalhe-do-contrato)
11. [Registrar pagamento (dar baixa)](#11-registrar-pagamento-dar-baixa)
12. [Cobrar hoje (`/cobrar-hoje/`)](#12-cobrar-hoje)
13. [Pix (`/pagamentos/pix/`)](#13-pix)
14. [Histórico de pagamentos (`/pagamentos/historico/`)](#14-histórico-de-pagamentos)
15. [Relatórios (`/relatorios/`) — só dono](#15-relatórios--só-dono)
16. [Admin (`/admin/`) — só equipe técnica](#16-admin--só-equipe-técnica)
17. [Rotina do dia sugerida](#17-rotina-do-dia-sugerida)
18. [Automações (o que o sistema faz sozinho)](#18-automações-o-que-o-sistema-faz-sozinho)
19. [Perguntas frequentes](#19-perguntas-frequentes)

---

## 1. Conceitos que aparecem em toda tela

### Perfis de acesso

| Perfil | Enxerga | Não enxerga |
|---|---|---|
| **Financeiro** | Início, Clientes, Contratos, Cobrar hoje, Pix, Histórico | Relatórios, Admin |
| **Dono** | Tudo do financeiro **+ Relatórios** | Admin (a não ser que também seja "equipe/staff") |
| **Equipe técnica (staff/superusuário)** | Tudo + **Admin** | — |

O dono vê tudo que o financeiro vê e ainda tem os Relatórios. O contrário não
vale. O perfil de cada usuário é definido no Admin (campo **perfil**).

### Estruturas de pagamento

Como as parcelas se repetem no tempo. A primeira parcela vence **um período
depois** da data de início (o dia da compra não conta como vencimento).

| Estrutura | Quando vence a parcela nº *n* | Observação |
|---|---|---|
| **Diária** | data de início + *n* dias | todo dia, domingo incluído |
| **Semanal** | data de início + 7×*n* dias | o atraso só começa **na segunda-feira** depois do domingo que fecha a semana |
| **Por dezena** | data de início + 10×*n* dias | "pegou dia 3, paga dia 13" |
| **Quinzenal** | data de início + 15×*n* dias | 15 dias corridos, não é "duas vezes no mês" |
| **Mensal** | mesmo dia do mês, mês a mês | 31/01 → cai em 28/02 nos meses curtos |

### Status e cores

O status é **recalculado toda vez que a tela abre**, com base na parcela em
aberto mais antiga do contrato.

| Selo | Cor | Significado |
|---|---|---|
| **Em dia** | verde | sem parcela vencida |
| **Atrasado** | vermelho | 1 a 6 dias de atraso |
| **Inadimplente** | vermelho | 7 dias de atraso ou mais |
| **Quitado** | cinza | contrato encerrado; parou de cobrar |

### Juros

- **R$ 5,00 fixos por dia de atraso** (5 × dias de atraso).
- Começa a contar **no dia seguinte** ao vencimento (vencer "hoje" ainda não é atraso).
- Na estrutura **semanal**, começa na segunda-feira após o domingo que fecha a semana.
- No atraso, a cobrança continua **todos os dias**.

### Alerta de bloqueio

Aos **7 dias de atraso** o sistema mostra **"⚠ hora de bloquear o aparelho"**.
O sistema **só avisa** — o bloqueio em si é ação manual do vendedor (Alisson).

### Parcela (Vencimento) × Pagamento (baixa)

- **Parcela / Vencimento**: o que o cliente *deve* pagar numa data (nº, data, valor previsto). O sistema gera automaticamente.
- **Pagamento / baixa**: o registro de que o dinheiro *entrou*. Você lança à mão.
- Cada parcela aceita **uma única baixa**. Para corrigir, use **estornar** e lance de novo.

### Dinheiro nos formulários

Digite com vírgula decimal: `1.234,56` ou `1234,56` ou `1234.56` — todos são
aceitos. O sistema mostra sempre com vírgula.

### Anexos (Comprovante e Documentos)

Os arquivos enviados em **Comprovante** (baixa) e **Documentos** (contrato) só
aceitam **PDF, JPG, JPEG, PNG ou WEBP**, até **10 MB**. Outro tipo de arquivo é
recusado com aviso na tela. O download exige estar **logado** — o link nunca
abre para quem não tem acesso ao sistema.

---

## 2. Entrar / Sair

**URL:** `/entrar/` · **Quem acessa:** todo mundo (é a porta de entrada).

Qualquer endereço do sistema sem login manda para esta tela.

**O que fazer:**
1. Digite **usuário** e **senha**.
2. Clique em **Entrar**.

- Usuário/senha errados → mensagem "Usuário ou senha inválidos."
- Depois de entrar, você cai na tela **Início** (resumo do dia). Se tinha
  tentado abrir outra página antes do login, o sistema te leva direto para ela.
- **Sair:** botão **Sair** no canto superior direito (ao lado do seu nome).
- Não há "criar conta" nem "esqueci a senha" na tela. Novos usuários e troca de
  senha são feitos pela equipe técnica no Admin.
- **Muitas tentativas erradas seguidas bloqueiam o acesso por segurança** (tela
  "Acesso bloqueado — Muitas tentativas"). O bloqueio se libera sozinho depois
  de cerca de **1 hora**; para liberar antes, é preciso pedir à equipe técnica
  (comando no servidor).

---

## 3. Barra de navegação

Aparece no topo de todas as páginas depois do login (fica **fixa no topo** ao
rolar a tela, também no celular):

| Link | Vai para | Quem vê |
|---|---|---|
| **Acompanhamento de Pagamentos** (título) | Início | todos |
| **Início** | Resumo do dia (números e gráficos) | todos |
| **Cobrar hoje** | Agenda de cobrança do dia | todos |
| **Pix** | Painel das cobranças Pix da Cora | todos |
| **Clientes** | Lista de clientes | todos |
| **Contratos** | Lista de contratos | todos |
| **Relatórios** | Painel de relatórios | só dono |
| **Admin** | Painel administrativo do Django | só equipe/staff |
| *(seu nome)* + **Sair** | Encerra a sessão | todos |

O link da seção em que você está fica destacado.

---

## 4. Início — resumo do dia

**URL:** `/` (também chamada de `relatorios:inicio`) · **Quem acessa:** todos
(financeiro e dono — diferente de Relatórios, que é só do dono).

Página que abre logo depois do login. Dá o retrato rápido do negócio sem
precisar entrar em Relatórios.

**Números do topo (do mês corrente, salvo indicação contrária):**
- **A receber em aberto** — soma de tudo que ainda não foi pago.
- **Em atraso (hoje)** — valor e quantidade de parcelas vencidas até hoje.
- **Recebido no mês** — quanto entrou, com o previsto do mês ao lado.
- **Contratos ativos** — quantidade (não quitados).
- **Inadimplentes** — quantidade de contratos com 7+ dias de atraso, com o
  total de atrasados (1+ dia) ao lado.
- **Ticket médio** — valor médio dos contratos.

**Gráficos:**
- **Recebido × previsto por mês** — barras dos últimos 6 meses.
- **Contratos por status** — rosca com a distribuição Em dia / Atrasado /
  Inadimplente / Quitado.

**"Precisa de atenção"** — tabela com os contratos em atraso agora (Cliente,
Contrato, dias de atraso, valor em aberto) e o link **registrar** direto para
a baixa. Sem ninguém atrasado, aparece "Nenhum contrato em atraso agora. 🎉".

**Botão "Ir para Cobrar hoje"** no topo leva direto para a agenda do dia.

---

## 5. Clientes — lista

**URL:** `/clientes/` · **Quem acessa:** todos.

Lista de todos os clientes cadastrados, em ordem alfabética, **20 por página**.

**Elementos da tela:**
- **Buscar por nome ou CPF** — digite parte do nome ou os números do CPF e clique **Buscar**. A busca é "contém" (não precisa ser exato).
- **Novo cliente** — botão à direita, abre o formulário de cadastro.
- **Tabela** com: Nome (link para a ficha), CPF formatado, Telefone (link `tel:` que disca no celular) e nº de Contratos.
- **Paginação** ("Anterior / Próxima") no rodapé quando há mais de 20.
- Se não houver ninguém (ou a busca não achar), aparece um aviso e o atalho para cadastrar.

**Ações a partir daqui:** clicar no nome abre a ficha; **Novo cliente** cadastra.

---

## 6. Clientes — novo / editar

**URLs:** `/clientes/novo/` e `/clientes/<id>/editar/` · **Quem acessa:** todos.

Mesma tela para cadastrar e para alterar (o título muda para "Editar cliente").

**Campos:**

| Campo | Obrigatório | Regras |
|---|---|---|
| **Nome completo** | Sim | livre, até 150 caracteres |
| **CPF** | Sim | só números; o sistema tira pontos e traços sozinho; **valida os dígitos** (CPF inválido é recusado); **não pode repetir** — dois clientes não podem ter o mesmo CPF |
| **Telefone / WhatsApp** | Sim | número brasileiro; usado para os links de ligação e de WhatsApp |
| **Endereço** | Não | livre |

**Botões:** **Salvar** (grava e vai para a ficha do cliente, com a mensagem
"Cliente cadastrado/atualizado") · **Cancelar** (volta sem gravar).

Erros de validação aparecem em vermelho embaixo do campo.

---

## 7. Clientes — ficha do cliente

**URL:** `/clientes/<id>/` · **Quem acessa:** todos.

Tudo sobre um cliente numa página só.

**Topo:**
- Nome do cliente.
- **Editar** — vai para o formulário.
- **Novo contrato** — abre o cadastro de contrato **já com este cliente preenchido**.

**Dados do cliente:** CPF, Telefone (link `tel:` que também é o número usado no
WhatsApp), Endereço, Data de cadastro.

**Contratos** — tabela de todos os contratos do cliente: Apelido (link),
Aparelho, Estrutura, Valor total e Status (selo colorido, recalculado na hora).

**Pagamentos** — os **50 pagamentos mais recentes** do cliente (todos os
contratos juntos): Data, Contrato, nº da parcela, Valor e Forma. Se houver mais
de 50, há o link **"ver histórico"** (abre o Histórico já filtrado por este
cliente).

Se o cliente não tem contratos ou pagamentos, cada bloco mostra um aviso curto.

---

## 8. Contratos — lista

**URL:** `/contratos/` · **Quem acessa:** todos.

Todos os contratos, ordenados por nome do cliente, **20 por página**.

**Elementos da tela:**
- **Filtro por status** — lista suspensa: Todos / Em dia / Atrasado / Inadimplente / Quitado. Muda a lista na hora. O filtro usa o status **calculado hoje** (o mesmo que a tela mostra).
- **Novo contrato** — botão à direita.
- **Tabela:** Apelido (link para o detalhe), Cliente (link para a ficha), Estrutura, Valor total, Início e Status.
- **Paginação** no rodapé.

---

## 9. Contratos — novo / editar

**URLs:** `/contratos/novo/` e `/contratos/<id>/editar/` · **Quem acessa:** todos.

Mesma tela para cadastrar e alterar. No topo há um bloco **"Como os campos de
parcela e datas funcionam"** que se abre ao clicar — vale a pena ler na primeira vez.

O formulário é dividido em quatro blocos:

### Cliente e aparelho
| Campo | Obrigatório | Observação |
|---|---|---|
| **Cliente** | Sim | escolha na lista; já vem preenchido se você veio do botão "Novo contrato" da ficha |
| **Apelido / descrição** | Sim | diferencia contratos do mesmo cliente. Ex.: "iPhone 11" |
| **Aparelho (modelo)** | Sim | ex.: "iPhone 11 64GB" |
| **IMEI** | Não | só números; o sistema tira o que não for dígito |

### Valores e estrutura
| Campo | Obrigatório | Observação |
|---|---|---|
| **Valor total do contrato** | Sim | com vírgula: `1.500,00` |
| **Estrutura de pagamento** | Sim | diária / semanal / por dezena / quinzenal / mensal |
| **Valor da parcela** | Não* | **digitado à mão** (o cálculo é feito fora do sistema). **Sem ele o sistema não gera as parcelas.** |
| **Nº de parcelas** | Não* | **digitado à mão**. Sem ele não há **data prevista de quitação** e a geração de parcelas usa um teto de segurança |

\* Não são obrigatórios para salvar, mas **sem os dois o contrato fica incompleto** (não gera parcelas / não calcula quitação).

> **Aviso de conferência:** se `valor da parcela × nº de parcelas` não bater com
> o valor total, aparece um aviso amarelo ("Parcela × nº dá R$ X, diferente do
> valor total"). É só um alerta — **o sistema não recalcula nada** e deixa você salvar.

### Datas
| Campo | Obrigatório | Observação |
|---|---|---|
| **Data de início** | Sim | base de todo o cronograma de parcelas |
| **Dia(s) de referência** | Não | anotação livre (ex.: "dia 15", "a cada 10 dias"). **Não entra no cálculo**, é só lembrete |
| **Próximo vencimento** | Não | data manual da próxima parcela. Só é usada para medir atraso/juros **enquanto o contrato ainda não tem parcelas geradas**. Depois disso quem manda é a parcela em aberto mais antiga |
| **Data prevista de quitação** | Não | normalmente **calculada pelo sistema** (data da última parcela). Só preencha à mão em casos especiais |

### Outros
| Campo | Observação |
|---|---|
| **Status** | em dia / atrasado / inadimplente / quitado. Em geral deixe "em dia" — o sistema recalcula sozinho nas telas. Use "quitado" só se quiser encerrar já no cadastro |
| **Observações** | texto livre |

**Ao salvar:** se o **valor da parcela** estiver preenchido, o sistema **já gera
as parcelas na hora** (até ~60 dias à frente), calcula a data prevista de
quitação e ajusta o status. Você vê mensagens tipo "3 parcela(s) gerada(s)
automaticamente". O botão "Gerar parcelas" no detalhe continua disponível como reforço.

---

## 10. Contratos — detalhe do contrato

**URL:** `/contratos/<id>/` · **Quem acessa:** todos.

A tela mais completa do sistema. De cima para baixo:

### Barra de ações (topo)
- **Ver cliente** — vai para a ficha.
- **Editar** — formulário do contrato.
- **Registrar pagamento** — dar baixa numa parcela (só aparece se o contrato **não** estiver quitado).

### Caixa "Marcar como quitado"
Aparece **só quando todas as parcelas previstas já estão pagas**. Traz o botão
**Marcar como quitado**.

> **Importante:** a baixa **nunca** quita o contrato sozinha. Quitar é **ação
> manual** (decisão do Alisson). Depois de quitado, o contrato para de cobrar,
> registra a data real de quitação e some da agenda "Cobrar hoje".

### Dados do contrato
Aparelho + IMEI, Estrutura, Telefone (com link WhatsApp), Status, Valor total,
**Parcela** (valor da parcela × nº de parcelas, ex.: "R$ 600,00 x 6"), Data de
início, Dia(s) de referência, Próximo vencimento, Previsão de quitação.

- Se `parcela × nº` não bate com o total, repete aqui o aviso de conferência.

### "Situação hoje"
Cartão com o retrato do dia:
- **Em dia** — "Sem atraso. Parcela nº X vence em dd/mm/aaaa."
- **Atrasado / Inadimplente** — "N dias de atraso (parcela nº X) · juros
  acumulados R$ Y".
- Aos 7+ dias: faixa vermelha **"⚠ N dias — hora de bloquear o aparelho (ação
  manual do vendedor)"**.
- Se não há como medir atraso (sem parcelas geradas e sem "próximo vencimento"),
  aparece o aviso para preencher o **próximo vencimento** no contrato.

### Parcelas
Tabela das parcelas geradas (mostra as **24 primeiras**): Nº, Vencimento,
Previsto, Pago, Saldo, Status (Em aberto / Parcial / Pago) e o link **"dar
baixa"** nas que ainda não estão pagas.

- **Botão "Gerar parcelas" / "Gerar parcelas seguintes":** cria as parcelas que
  faltam **até 60 dias à frente**, a partir da data de início + estrutura.
  Pode clicar de novo mais tarde para gerar as próximas. É **idempotente**
  (clicar duas vezes não duplica nada).
- Se **não há parcelas** e falta o **valor da parcela**, a tela pede para editar
  o contrato e preencher esse campo primeiro.

### Saldo transportado
Aviso que aparece **só quando existe** saldo de um pagamento parcial (ou de um
pagamento a maior) que não achou parcela seguinte onde encaixar. Esse valor
entra automaticamente na **próxima parcela gerada**.

### Pagamentos
Tabela de todas as baixas do contrato: Data, Parcela, Valor, Forma, quem deu a
baixa e quando, link **baixar** do comprovante (se anexado) e o botão **estornar**.

- **Estornar** pede confirmação. Desfaz a baixa, devolve a parcela para
  "em aberto/parcial" e recalcula o status.
- Se a baixa estornada havia **transportado saldo** para parcelas seguintes, o
  sistema **avisa** que os valores previstos das próximas parcelas precisam ser
  conferidos **à mão** (ele não desfaz o transporte sozinho).

### Documentos
Tabela dos arquivos anexados (Tipo, Descrição, link **baixar**, quem enviou e
quando) e o formulário **"Anexar documento"**:
- **Tipo:** Contrato assinado / RG / Comprovante de residência / Outro.
- **Arquivo:** PDF, JPG, JPEG, PNG ou WEBP, até 10 MB (ver [seção 1](#1-conceitos-que-aparecem-em-toda-tela)).
- **Descrição:** opcional.
- Clique **Anexar documento**. O sistema guarda quem enviou e a data.
- Os links de download (**baixar**) exigem login — não são links públicos.

---

## 11. Registrar pagamento (dar baixa)

**URL:** `/pagamentos/contrato/<id>/novo/` · **Quem acessa:** todos.
Chega-se aqui pelo botão **Registrar pagamento** (detalhe do contrato), pelo
link **"dar baixa"** numa parcela, pelo link **"Registrar pagamento"** da
agenda "Cobrar hoje" ou pelo link **"registrar"** na lista "Precisa de
atenção" da tela **Início**.

Se o contrato estiver **quitado**, o sistema recusa e volta para o detalhe.

**Cabeçalho:** Cliente, Contrato + estrutura, Valor da parcela.

**Formulário:**
| Campo | Preenchimento | Regras |
|---|---|---|
| **Parcela** | já vem selecionada a **mais antiga em aberto**; a lista mostra "Parcela N · vence dd/mm/aaaa · falta R$ X" | só aparece parcelas não pagas; se a parcela escolhida já tiver baixa, o sistema recusa e manda estornar a anterior |
| **Data do pagamento** | vem com **hoje** | **não pode ser no futuro** |
| **Valor pago** | vem com o **saldo da parcela** | tem que ser **maior que zero** |
| **Forma** | Pix / Dinheiro / Outro | padrão: Pix |
| **Comprovante** | opcional | anexo — PDF, JPG, JPEG, PNG ou WEBP, até 10 MB |
| **Observação** | opcional | texto livre |

**Botões:** **Registrar baixa** · **Cancelar**.

**O que acontece ao registrar:**
- **Valor igual ao saldo** → parcela vira **Pago**.
- **Valor menor** (pagamento parcial) → parcela vira **Parcial**; o que faltou é
  **somado ao valor previsto da próxima parcela em aberto** (ou vira "saldo
  transportado" se não houver próxima).
- **Valor maior** (pagou a mais) → o troco **abate as próximas parcelas** (em
  cascata), ou vira crédito no "saldo transportado".
- Se, com essa baixa, **todas as parcelas** ficarem pagas, o sistema avisa para
  usar **"Marcar como quitado"** no detalhe — mas **não quita sozinho**.

Abaixo do formulário há a tabela **"Parcelas em aberto"** (as 8 primeiras) para consulta.

---

## 12. Cobrar hoje

**URL:** `/cobrar-hoje/` (ou `/pagamentos/cobrar-hoje/`) · **Quem acessa:** todos.

A agenda de trabalho do dia. Lista os contratos **atrasados** (qualquer
estrutura) **ou** com **vencimento hoje**. Contratos quitados nunca aparecem.

**Resumo do topo (números do dia):**
- **Para cobrar** — quantos contratos na lista.
- **Atrasados** — quantos já passaram do vencimento.
- **Alerta de bloqueio** — quantos com 7+ dias de atraso.
- **Total previsto (parcela + juros)** — soma do que dá para receber hoje.

**Tabela** (ordenada por dias de atraso, do maior para o menor):

| Coluna | O que mostra |
|---|---|
| **Cliente** | nome (link para a ficha) |
| **Contrato** | apelido (link) + estrutura |
| **Situação** | "Vence hoje" (verde) **ou** selo do status + selo "⚠ bloquear aparelho" (lado a lado, quando for o caso) + "N dias de atraso" em destaque numa linha própria |
| **A cobrar** | valor da parcela + juros; a linha de baixo detalha "parcela R$ X + juros R$ Y". Se não houver valor de parcela no contrato, mostra "só juros R$ Y · defina o valor da parcela no contrato" |
| **Envio** | dois selos: **Pix** (estado da cobrança Cora da parcela) e **Msg** (estado da mensagem de WhatsApp do dia). "não gerado / não preparada" quando ainda não existem. Passe o mouse para ver o detalhe |
| **Contato** | ícone de telefone (link de ligação), ícone de WhatsApp, e o botão **Registrar** (baixa) |

**Como usar:** percorra a lista, entre em contato pelo WhatsApp/telefone e, quando
o cliente pagar, clique em **Registrar** naquela linha para dar baixa.

Se não há nada: **"Nada para cobrar hoje. 🎉"**

---

## 13. Pix

**URL:** `/pagamentos/pix/` · **Quem acessa:** todos.

Acompanhamento das cobranças **Pix automáticas da Cora**. Cada parcela pode
receber uma cobrança Pix; quando a Cora confirma o pagamento, a **baixa é
automática** (você não precisa lançar nada).

**Resumo do topo:**
- **Na tela** — total de linhas exibidas.
- **✅ Pagos hoje** — confirmados pela Cora hoje.
- **⏳ Aguardando** — cobrança gerada, cliente ainda não pagou.
- **❌ Não pagos** — a cobrança **venceu** sem pagamento → o financeiro deve
  entrar em contato.
- **⚠ Erros** — falha ao gerar/processar a cobrança.

**Tabela:** Cliente (link), Contrato (link), nº da Parcela, Vencimento, Valor,
Status (com selo colorido) e **Pix** — o botão **"Copiar código"** copia o
código Pix copia-e-cola para a área de transferência, pronto para colar e
mandar ao cliente.

A tela mostra as cobranças **pendentes, aguardando, não pagas e com erro**, além
das **pagas hoje**. Cobranças pagas em dias anteriores não poluem a lista.

> Enquanto a integração da Cora estiver em modo seguro (`CORA_PROVIDER=log`),
> nada é enviado de verdade. Ativação em `docs/CORA.md`.

---

## 14. Histórico de pagamentos

**URL:** `/pagamentos/historico/` · **Quem acessa:** todos.

Todas as baixas já registradas, da mais recente para a mais antiga, **50 por
página**.

**Colunas:** Data, Cliente (link), Contrato (link), nº da Parcela, Valor, Forma,
e **Baixa** (quem lançou + data/hora).

**Filtros** (chegam pela URL, normalmente ao clicar "ver histórico" numa ficha):
- `?cliente=<id>` — só as baixas daquele cliente.
- `?contrato=<id>` — só as daquele contrato.
- Quando um filtro está ativo, aparece **"Filtrado · ver todos"** para limpar.

Paginação com "Anterior / Próxima" preservando o filtro.

---

## 15. Relatórios — só dono

**URL:** `/relatorios/` · **Quem acessa:** **só perfil dono** (financeiro recebe
"acesso negado"). Não confundir com a tela **Início**, que também mostra
números-chave mas é aberta para todos.

Consolidação de um período.

### Filtro
| Campo | Uso |
|---|---|
| **Período** | Diário / Semanal / Mensal / Personalizado |
| **Data de referência** | o dia base. Diário = esse dia; Semanal = a semana (segunda a domingo) que o contém; Mensal = o mês inteiro |
| **Início / Fim (personalizado)** | só quando o período é "Personalizado". Fim não pode ser antes do Início; máximo de 367 dias |

Clique **Atualizar**. Sem nenhum filtro, o padrão é **o dia de hoje**.

### Indicadores do período
- **Previsto no período** — soma dos valores previstos das parcelas que vencem no intervalo.
- **Recebido no período** — soma das baixas com data de pagamento no intervalo.
- **Total em atraso** — soma em aberto das parcelas vencidas **até o fim do período** (retrato histórico: uma parcela paga depois do fim do período ainda conta como atrasada aqui).
- **Parcelas atrasadas** — quantidade das acima.
- **Novos clientes** — cadastrados no intervalo.
- **Contratos quitados** — marcados como quitados no intervalo.

### Tabelas
- **Recebimentos por forma** — Pix / Dinheiro / Outro, com quantidade e total.
- **Recebimentos** — cada baixa: Data, Cliente, Contrato, Forma, Valor.
- **Parcelas em atraso até o fim do período** — Cliente, Contrato, Vencimento, nº, Em aberto.

### Exportar
- **Baixar Excel** — arquivo `.xlsx` com abas **Resumo**, **Recebimentos** e **Em atraso**.
- **Baixar PDF** — mesmo conteúdo em PDF paisagem.

Os dois botões respeitam o período que está na tela.

---

## 16. Admin — só equipe técnica

**URL:** `/admin/` · **Quem acessa:** usuários marcados como **equipe (staff)** ou **superusuário**.

Painel administrativo do Django. Uso principal:

- **Usuários** — criar logins, definir **perfil** (financeiro / dono), marcar
  quem é equipe/staff, **trocar senha**, ativar/desativar acesso.
- **Clientes** — cadastro completo **com importação e exportação** (CSV/Excel):
  botões **Importar** e **Exportar** no topo da lista. Busca por nome, CPF ou telefone.
- **Contratos** — idem, com **importação e exportação**. Busca por nome/CPF do
  cliente, apelido, aparelho ou IMEI.
- **Vencimentos, Pagamentos, Cobranças (WhatsApp), Cobranças Cora, Eventos Cora** —
  consulta e ajuste fino quando algo precisa ser corrigido manualmente.

> O Admin é uma ferramenta técnica: alterações aqui não passam pelas validações
> e avisos das telas normais. Use com cuidado e, de preferência, só a
> importação/exportação de clientes e contratos e a gestão de usuários.

---

## 17. Rotina do dia sugerida

1. **Início** — dê uma olhada rápida nos números do dia e em "Precisa de atenção".
2. **Cobrar hoje** — abra a agenda. Veja os números do topo.
3. Para cada linha: contate o cliente (WhatsApp/telefone).
4. **Pix** — confira os **"❌ Não pagos"** e os **"⚠ Erros"**; entre em contato nesses casos. Os **"✅ Pagos hoje"** já entraram sozinhos.
5. Quando alguém pagar fora do Pix: **Registrar pagamento** na linha correspondente.
6. Contrato com **todas as parcelas pagas** → abra o detalhe e clique **Marcar como quitado**.
7. Cadastros do dia (novos clientes / contratos) entram por **Clientes → Novo** e **Contratos → Novo**.
8. Fim de mês / a pedido do dono: **Relatórios** e exportação em Excel/PDF.

---

## 18. Automações (o que o sistema faz sozinho)

Rodam no servidor uma vez por dia (não precisam de ação sua):

| Tarefa | O que faz |
|---|---|
| **Gerar vencimentos** | cria as parcelas que faltam até ~60 dias à frente, atualiza a data prevista de quitação e o status de todos os contratos |
| **Lembrete diário** | monta o resumo do dia para a Yslane |
| **Cobrança dos clientes** | prepara e envia (quando a Evolution API está ligada) as mensagens de vencimento/atraso pelo WhatsApp |
| **Reconciliação Cora** | confere na Cora as cobranças Pix abertas e registra as baixas confirmadas |

Por padrão os envios ficam em **modo seguro** (`WHATSAPP_PROVIDER=log` /
`CORA_PROVIDER=log`): as filas são criadas e aparecem nos painéis, mas **nada
sai do sistema** até a equipe técnica ativar cada integração (`docs/WHATSAPP.md`,
`docs/CORA.md`).

---

## 19. Perguntas frequentes

**Lancei uma baixa errada. E agora?**
No detalhe do contrato, seção **Pagamentos**, clique **estornar** na linha. Se
aparecer o aviso de saldo transportado, confira à mão os valores previstos das
parcelas seguintes.

**O cliente pagou só uma parte. Posso registrar?**
Pode. A parcela fica **Parcial** e a diferença entra na próxima parcela
automaticamente.

**Por que o contrato não gera parcelas?**
Falta o **valor da parcela** no cadastro. Edite o contrato, preencha e salve (ou
use o botão **Gerar parcelas** no detalhe).

**A baixa quitou o contrato?**
Não. Quitar é sempre **manual**: botão **Marcar como quitado** no detalhe, que só
aparece quando todas as parcelas previstas estão pagas.

**Mudei o status do contrato no formulário e ele "voltou".**
Normal. O status é **recalculado** toda vez que a tela abre, a partir das
parcelas em aberto. O campo no formulário só vale para casos manuais (ex.: quitar).

**"Cobrar hoje" está diferente de "Pix".**
São coisas diferentes: **Cobrar hoje** é a agenda de quem contatar (atraso +
vencimento do dia); **Pix** é o acompanhamento das cobranças automáticas da Cora.

**"Início" está diferente de "Relatórios".**
**Início** é o resumo rápido do dia/mês, aberto para financeiro e dono.
**Relatórios** é a consolidação detalhada e exportável de um período à
escolha, só para o dono.

**Não consigo ver Relatórios.**
Relatórios é **só para o perfil dono**. Peça à equipe técnica para ajustar seu
perfil no Admin.

**Como cadastro um novo usuário do sistema?**
Só pelo **Admin** (`/admin/` → Usuários), por quem tem acesso de equipe/staff.

**Errei a senha várias vezes e travou.**
É a proteção contra tentativas de invasão (bloqueio automático). Espere cerca
de 1 hora ou peça à equipe técnica para liberar antes pelo servidor.
