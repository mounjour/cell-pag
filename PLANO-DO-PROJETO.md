# Plano do Projeto — Sistema de Acompanhamento de Pagamentos de Celulares

> **Anteprojeto** · 28/08/2026 (atualizado com as respostas do formulário de 28/08)
> **Base:** "Roteiro de Entrevista com Yslane v2" + "Respostas" + formulário de respostas da Yslane
> **Status:** Blocos 4–8 respondidos pela Yslane. Falta só o Alisson definir: cálculo da
> parcela, regra da **diária**, regra da **por dezena** e regra exata do **mensal**.

Site para controlar os pagamentos dos aparelhos vendidos a prazo — nas estruturas
**diária, semanal, por dezena, quinzenal e mensal**. Uso principal de **Yslane** (financeiro),
com acesso de **Alisson Erllen** (dono) para consultas e definição de acordos.

Este documento é a fonte de contexto para a construção do projeto. Onde houver
`[A CONFIRMAR]` ou `[NÃO DEFINIDO]`, **não assumir** — a regra precisa ser fechada com
Alisson e/ou Yslane antes de codar.

## Índice

1. [Contexto atual](#1-contexto-atual)
2. [Objetivos do sistema](#2-objetivos-do-sistema)
3. [Escopo](#3-escopo)
4. [Módulos funcionais](#4-módulos-funcionais)
5. [Estruturas de pagamento](#5-estruturas-de-pagamento)
6. [Modelo de dados proposto](#6-modelo-de-dados-proposto)
7. [Arquitetura técnica proposta](#7-arquitetura-técnica-proposta)
8. [Cobrança automática — decisão de canal](#8-cobrança-automática--decisão-de-canal)
9. [Roadmap de entrega](#9-roadmap-de-entrega)
10. [Pendências da entrevista](#10-pendências-da-entrevista)
11. [Riscos e mitigações](#11-riscos-e-mitigações)
12. [Próximos passos imediatos](#12-próximos-passos-imediatos)
13. [Stack técnica](#13-stack-técnica)
14. [Backlog — o que falta](#14-backlog--o-que-falta)

---

## 1. Contexto atual

Hoje o controle é feito em **planilha e WhatsApp**, sem histórico estruturado nem visão
consolidada de atrasos.

- **Mais de 25 clientes ativos** de celulares, com expectativa de crescimento.
- Existe também acompanhamento de **~25 motos** — **fora da v1** (Alisson, 02/09): esta versão é **só celulares**. O contrato fica modelado de forma genérica (campo produto) para as motos entrarem numa fase futura.
- Contrato é assinado fisicamente; anexar a **foto do contrato** é desejável, mas opcional.

### Dores que o sistema precisa resolver

- **Acompanhar as cobranças diárias** — apontado pela Yslane como a maior dificuldade e como o
  item que **não pode faltar** na v1: não se perder com as datas e com quantos dias de atraso cada um está.
- Esquecer de cobrar alguém no dia.
- Cobrança duplicada (cobrar de novo quem já pagou).
- Falta de acompanhamento individual dos atrasos de cada cliente.

### Quem usa

- **Yslane — financeiro:** uso diário; cadastra clientes, registra pagamentos, faz as cobranças. Acessa **principalmente pelo celular**.
- **Alisson — dono:** consulta relatórios e define os acordos de valor, prazo e estrutura, e o cálculo das parcelas.
- Ninguém mais precisa de acesso por enquanto.

---

## 2. Objetivos do sistema

- Centralizar o cadastro de clientes e de contratos/aparelhos.
- Gerar automaticamente os vencimentos conforme a estrutura de pagamento de cada contrato.
- Registrar cada pagamento recebido como um lançamento individual (uma linha por pagamento) — o histórico.
- Produzir todo dia a lista de **"quem cobrar hoje"** e enviar como lembrete para a Yslane às 08:30.
- Calcular dias de atraso, **juros de R$ 5,00/dia** e o status (verde / vermelho).
- Oferecer relatórios diários, semanais e mensais, com exportação.
- Calcular a data prevista de quitação e encerrar a cobrança quando o contrato é quitado.

---

## 3. Escopo

### Dentro da primeira versão (MVP)

- **Layout mobile-first** — a Yslane usa principalmente no celular.
- Cadastro de cliente: nome, CPF e telefone/WhatsApp obrigatórios; endereço opcional.
- Cadastro de contrato/aparelho, com **vários contratos por cliente**.
- As 5 estruturas de pagamento, com geração automática de vencimentos.
- Registro de pagamentos vinculado à parcela (nº + data), **aceitando pagamento parcial**
  (o saldo não pago é somado ao próximo pagamento).
- Painel diário "cobrar hoje" + lembrete para a Yslane às 08:30.
- Contagem de dias de atraso, juros de **R$ 5,00/dia** e status visual (verde / vermelho).
- Relatório diário e mensal, com exportação (Excel/PDF).
- Login para Yslane e Alisson.

### Fora do MVP — fases seguintes

- Envio 100% automático de mensagem direto ao cliente no WhatsApp (depende da decisão de canal — ver [seção 8](#8-cobrança-automática--decisão-de-canal)).
- Módulo de motos.
- Portal ou app para o cliente acompanhar o próprio contrato.
- Geração dinâmica de chave Pix e conciliação bancária automática.
- Recálculo automático de saldo na troca de estrutura no meio do contrato — validar a regra antes de construir.

---

## 4. Módulos funcionais

### 4.1 — Cadastro de clientes

| Campo | Obrigatório | Observações |
| :---- | :---- | :---- |
| Nome completo | Sim | — |
| CPF | Sim | Identificação principal do cliente. |
| Telefone / WhatsApp | Sim | Usado pela cobrança. |
| Endereço | Não | Opcional, mas útil para visita/recolhimento. |

### 4.2 — Contratos / aparelhos

Um cliente pode ter **mais de um contrato ativo**. Hoje eles são diferenciados pelo nome do
aparelho — ex.: "Ronildo iPhone 11" e "Ronildo iPhone 13". O sistema deve tratar cada
contrato como um registro próprio, vinculado ao cliente.

| Campo | Situação | Observações |
| :---- | :---- | :---- |
| Apelido / descrição do contrato | Definido | Ex.: "iPhone 11". Diferencia contratos do mesmo cliente. |
| Aparelho (modelo / IMEI) | Definido | IMEI ajuda em caso de recolhimento. |
| Valor total do contrato | Definido | Base do cálculo da parcela. |
| Estrutura de pagamento | Definido | Diária / semanal / dezena / quinzenal / mensal. |
| Valor da parcela | Definido (Alisson, 03/09) | **Manual.** Calculado fora do sistema (GPT "vendas dos celulares"); o sistema só armazena. |
| Data de início | Definido | Referência para gerar os vencimentos. |
| Nº / identificador único do contrato | Definido (Alisson, 02/09) | **Não existe** hoje. Opcional: o sistema pode gerar um nº interno; não é obrigatório para o negócio. |
| Fiador / avalista | Definido (Alisson, 02/09) | **Não usar** — sem campo no cadastro. |
| Documentos anexados | Definido | Foto do contrato (opcional). |
| Status | Definido | Em dia / atrasado / inadimplente / quitado. Cor: verde (em dia) / vermelho (atraso). |
| Data prevista de quitação | Definido | Calculada automaticamente pelo sistema a partir da estrutura. |

### 4.3 — Estruturas e geração de vencimentos

Detalhado na [seção 5](#5-estruturas-de-pagamento). É o núcleo da lógica: define quando e quanto cobrar.

### 4.4 — Registro de pagamentos

Cada pagamento recebido gera **uma linha própria**, separada do cadastro — é o que alimenta
o histórico e os relatórios.

| Campo | Observações |
| :---- | :---- |
| Data do pagamento | Obrigatório. |
| Cliente / nº do contrato | Vínculo obrigatório. |
| Parcela / período referente | **Vinculado à parcela específica** (nº da parcela + data). |
| Valor pago | — |
| Forma de pagamento | Pix, dinheiro, outro. |
| Quem deu baixa | Usuário logado (ou o sistema, na baixa automática) — trilha de auditoria contra cobrança duplicada. |
| Comprovante anexado | **Não obrigatório.** Campo opcional. |
| Pagamento total ou parcial | **Parcial é aceito.** O valor que faltou vira débito **somado ao próximo pagamento** do contrato. |
| Observações / atraso | Texto livre. |

**Histórico completo por cliente:** obrigatório — mostra todos os pagamentos desde o início do contrato.

### 4.5 — Cobrança automática

Detalhado na [seção 8](#8-cobrança-automática--decisão-de-canal).

### 4.6 — Atraso e inadimplência

- Contagem automática de dias de atraso por parcela.
- **Juros: R$ 5,00 fixos por dia de atraso**, por contrato/parcela (valor por dia × dias de atraso).
- **Aos 7 dias de atraso:** o aparelho é bloqueado. O sistema **apenas alerta** a Yslane/Alisson;
  o **bloqueio é ação manual do vendedor** (Alisson, 02/09) — sem integração. É o gatilho de "ação mais forte".
- **Cobrança no atraso:** o sistema **continua cobrando todo dia** até o cliente pagar (não muda a mensagem).
- **Status visual:** verde = em dia · vermelho = atrasado/inadimplente. Sugerido: cinza para quitado.
  Continuar guardando os 4 status internamente (em dia / atrasado / inadimplente / quitado).

#### Estado da implementação (04/09)

- **Lógica pura pronta** em `apps/pagamentos/atraso.py` — funções sem banco, cobertas por
  testes: `dias_de_atraso` (com a janela da **semanal**: atraso só a partir da segunda
  seguinte ao domingo que fecha a semana), `juros_acumulados` (R$ 5,00/dia),
  `classificar_status` (os 4 status), `cor_do_status` (verde/vermelho/cinza),
  `precisa_alertar_bloqueio` (≥ 7 dias) e `avaliar` (junta tudo num `SituacaoAtraso`).
- **Ligada ao `Contrato`** — métodos `parcela_em_aberto()` (a parcela `Vencimento` de menor
  nº ainda não paga), `data_referencia_atraso()` (a data dessa parcela, ou o
  `proximo_vencimento` manual quando o contrato ainda não tem vencimentos gerados),
  `situacao_atraso(hoje)`, `status_efetivo` e `sincronizar_status(hoje)`. O detalhe do
  contrato mostra o bloco "Situação hoje" (dias, juros, nº da parcela, alerta de bloqueio);
  o admin tem a coluna "atraso hoje".
- **Inferência a confirmar com o Alisson:** a fronteira "atrasado → inadimplente" está no
  mesmo ponto do gatilho de bloqueio (7 dias), isolada na constante `LIMITE_INADIMPLENTE`.
  O formulário só definiu o gatilho dos 7 dias, não a fronteira dos status.
- **Feito:** o `status` salvo no `Contrato` (usado na lista e no filtro) é atualizado em
  massa pelo **job diário** `manage.py gerar_vencimentos` (Fase 2), via `sincronizar_status`.
  O cálculo agora usa a **parcela específica** em aberto (`Vencimento`) quando ela existe,
  em vez de só a data manual `proximo_vencimento` (que segue como *fallback*).

### 4.7 — Relatórios

- **Visão do dia (prioridade nº 1):** a **lista de clientes para cobrar no dia correspondente**.
  Somar também: total previsto para receber, total já recebido, atrasados do dia.
- **Semanal / mensal:** total recebido, total em atraso, novos clientes, contratos quitados. **Necessário.**
- Exportação em Excel e PDF para compartilhar. **Necessário.**

### 4.8 — Usuários e acesso

- Login individual para Yslane (perfil financeiro) e Alisson (perfil dono, foco em relatórios).
- **Acesso principal pelo celular** (a Yslane usa quase sempre no celular); também funciona no
  computador. Mesma URL, layout responsivo mobile-first.

---

## 5. Estruturas de pagamento

São **5 estruturas**. As 5 regras de vencimento estão **definidas** — Yslane (28/08),
Alisson (02/09 semanal; 03/09 diária, dezena, mensal).

| Estrutura | Regra de vencimento | Dia(s) de referência | Definição |
| :---- | :---- | :---- | :---- |
| **Diária** | Cliente paga **todo dia, sem folga** — domingo inclusive. | Todos os dias | **Definido (Alisson, 03/09):** "não, é todo dia." Sem dia de folga. |
| **Semanal** | 1× por semana; sem dia fixo — paga durante a semana quando dá. | Semana (dom→dom) | **Definido (Alisson, 02/09):** janela até o fim da semana. A parcela da semana só conta como atraso **depois de domingo** — atraso começa na segunda-feira seguinte, e os R$ 5,00/dia contam a partir dela. |
| **Por dezena** | A cada **10 dias corridos** a partir da **data de início**. | `data_inicio + 10·n` | **Definido (Alisson, 03/09):** "dez dias após ele pegar o celular — pegou dia 3, paga dia 13, e assim sucessivamente." Não são períodos fixos do mês. |
| **Quinzenal** | A cada **15 dias corridos** a partir da **data de início**. | `data_inicio + 15·n` | **Definido (Alisson, 03/09 → confirmado na Fase 2):** mesma lógica da dezena, com passo de 15 dias. `dia_referencia` é só anotação livre. |
| **Mensal** | 1× por mês, **no mesmo dia do mês da `data_inicio`**, recorrente. | `data_inicio + relativedelta(months=n)` | **Definido (Alisson, 03/09 → confirmado na Fase 2):** "o cliente decide a data" — grava-se essa data na `data_inicio`. Meses curtos caem no último dia (31/01 → 28/02). |

### Regras transversais

- **Cálculo da parcela:** **feito fora do sistema** (Alisson, 03/09: "tem um GPT
  'vendas dos celulares', o cálculo é feito lá; podemos colocar isso de forma manual").
  Não há fórmula fixa — é precificação caso a caso por metas de margem/rentabilidade
  (histórico: ~50% de margem / ~80% de rentabilidade sobre o custo, entrada + N parcelas).
  **O sistema não calcula:** `valor_parcela` e `num_parcelas` são campos **manuais** por contrato.
- **Escolha e troca de estrutura:** o cliente escolhe na compra e a estrutura é
  **fixa** (Alisson, 03/09: "não ocorre; isso é fixo. Caso de quebra, precisa refazer").
  **Não há troca de estrutura nem recálculo de saldo no meio do contrato** — se precisar
  mudar, refaz-se o contrato. O sistema não precisa de lógica de recálculo.
- **Data prevista de quitação:** calculada pelo sistema a partir da estrutura + `data_inicio`
  + `num_parcelas` (data do último vencimento gerado).
- **Ao quitar** todas as parcelas: marcar o contrato como "quitado" e **parar a cobrança
  automática** (Yslane: "Sim"). — RESOLVIDO.

---

## 6. Modelo de dados proposto

Entidades principais e seus campos-chave. Serve de base para a modelagem do banco.

| Entidade | Campos-chave |
| :---- | :---- |
| **Cliente** | `id · nome · cpf · telefone_whatsapp · endereco? · criado_em` |
| **Contrato** | `id · cliente_id · apelido · aparelho_modelo · imei? · valor_total · estrutura · valor_parcela · num_parcelas · data_inicio · dia_referencia? · fiador? · status · data_prevista_quitacao` |
| **Vencimento** (parcela) | `id · contrato_id · numero · periodo_referencia · data_vencimento · valor_previsto · valor_pago · dias_atraso · status` |
| **Pagamento** | `id · contrato_id · vencimento_id? · data_pagamento · valor_pago · forma · usuario_baixa · comprovante? · tipo(total/parcial) · observacao` |
| **Cobranca** (notificação) | `id · contrato_id · data_alvo · canal(whatsapp/lembrete) · status(pendente/enviado/erro) · mensagem · enviado_em` |
| **Anexo** | `id · referencia(cliente/contrato/pagamento) · tipo · arquivo` |
| **Usuario** | `id · nome · email · perfil(financeiro/dono) · senha_hash` |
| **ConfigCobranca** | `horario_envio (08:30) · texto_padrao (Yslane vai enviar) · numero_whatsapp (pessoal da Yslane) · juros_por_dia (R$ 5,00) · dias_para_bloqueio (7)` |

**Regras de negócio já fixadas (formulário de 28/08):**

- `juros_por_dia = 5.00` (BRL), aplicado por dia de atraso.
- `dias_para_bloqueio = 7` — aos 7 dias de atraso o aparelho é bloqueado (ação sinalizada pelo sistema).
- `horario_envio = 08:30` — envio do lembrete diário para a Yslane.
- Pagamento parcial gera saldo que é somado ao próximo pagamento do mesmo contrato.
- Baixa: automática quando o sistema conseguir detectar o pagamento; caso contrário, manual.

O produto do contrato (celular / moto) fica como um campo — assim o módulo de motos entra
depois sem reescrever o modelo.

---

## 7. Arquitetura técnica proposta

- **Aplicação web responsiva**, mesma URL para Yslane e Alisson, funcionando em celular e computador.
- **Banco relacional** (PostgreSQL) — dado financeiro estruturado, com relatórios e histórico.
- **Rotina agendada diária** (job/cron): de madrugada, gera os vencimentos do dia e monta a fila de cobrança.
- **Autenticação** com login/senha por usuário e perfis de acesso.
- **Hospedagem em nuvem** com **backup diário** do banco — não pode perder dado financeiro.
- **Trilha de auditoria**: todo registro de baixa guarda quem fez e quando (ataca a cobrança duplicada).
- **Exportação** de relatórios em Excel e PDF.
- **Integração WhatsApp**: ver decisão de canal na [seção 8](#8-cobrança-automática--decisão-de-canal).

O back-end será feito em **Django**. A stack completa recomendada está na [seção 13](#13-stack-técnica).
O que o plano fixa como princípio é: web responsiva, banco relacional, job diário, backup e auditoria.

---

## 8. Cobrança automática — decisão de canal

Respostas da Yslane (formulário de 28/08):

| Ponto | Resposta |
| :---- | :---- |
| Mensagem direta ao cliente x lembrete para a Yslane | **Lembrete para a Yslane** é a preferência; "os dois seria ótimo". |
| Horário de envio | **08:30 da manhã**. |
| Conteúdo da mensagem ao cliente | A Yslane vai **preparar o texto final**. Até lá, usar o **rascunho provisório** abaixo (Alisson, 02/09). |
| Número de origem (se enviar ao cliente) | **Número pessoal da Yslane**. |
| Quem dá a baixa | **O próprio sistema**, se conseguir saber que o pagamento entrou; senão, baixa manual. |
| Cliente não paga no dia | **Continua cobrando todo dia** (não muda a mensagem). |
| Varia por cliente? | **Não** (Alisson, 02/09). A configuração de canal/mensagem é global, sem variação por cliente. |

### Modalidade A — Lembrete para a Yslane `[BASE DA V1]`

Todo dia às 08:30 o sistema monta a **lista de clientes para cobrar naquele dia** e envia um
resumo para a Yslane (na tela ao abrir o sistema, e **pelo WhatsApp** — decisão do Alisson,
04/09; a ideia anterior de Telegram/e-mail não vale mais). A Yslane cobra manualmente. Pode
incluir um botão "abrir no WhatsApp" com o texto já pronto por cliente.

**Estado da implementação (04/09):** a agenda do dia e o texto do resumo já são montados
automaticamente (`apps/pagamentos/agenda.py` + `apps/pagamentos/lembrete.py`,
`manage.py enviar_lembrete_diario`). **O envio de verdade ainda não existe** — falta a conta no
WhatsApp Business Cloud API (Meta ou BSP como 360dialog/Zenvia: verificação de empresa +
template aprovado, igual à Modalidade B). Decisão do Alisson (04/09): **"deixar pronto, sem
conta ainda"** — `lembrete.enviar()` é um stub que só loga o texto; trocar pelo envio real
quando a conta existir, sem mexer no resto do fluxo.

### Texto da mensagem `[RASCUNHO PROVISÓRIO — substituir pelo texto da Yslane]`

Rascunho para o botão "abrir no WhatsApp". Placeholders entre `{}` preenchidos pelo sistema.
Chave Pix e forma de pagamento a confirmar com a Yslane.

**Lembrete no dia do vencimento:**

> Oi, {nome}! Passando pra lembrar que hoje ({data_venc}) vence a parcela {n_parcela} do seu {aparelho}, no valor de R$ {valor}. Você pode pagar via Pix ({chave_pix}) e me mandar o comprovante por aqui. Qualquer dúvida é só chamar. Obrigada!

**Cobrança em atraso (1 a 6 dias):**

> Oi, {nome}! A parcela {n_parcela} do seu {aparelho}, que venceu em {data_venc}, está em aberto ({dias_atraso} dia(s) de atraso). Com os R$ 5,00/dia, o valor atualizado está em R$ {valor_com_juros}. Assim que der, faz o Pix ({chave_pix}) e me envia o comprovante. Se já pagou, é só desconsiderar. Obrigada!

**Aviso de bloqueio (7 dias de atraso):**

> Oi, {nome}! A parcela {n_parcela} do seu {aparelho} está com {dias_atraso} dias de atraso. Preciso que seja regularizada hoje para evitar o bloqueio do aparelho. Valor atualizado: R$ {valor_com_juros} — Pix ({chave_pix}). Me chama se precisar de ajuda pra resolver.

### Modalidade B — Mensagem direto ao cliente `[FASE 6 / desejável]`

Enviar a mensagem automática ao cliente no dia do vencimento. A Yslane toparia usar o
**número pessoal dela**, mas isso via ferramenta não oficial tem **risco de bloqueio da conta**
— por isso a Modalidade B fica para depois, preferencialmente com **provedor oficial**
(WhatsApp Cloud API). Depende do texto padrão que a Yslane vai enviar.

---

## 9. Roadmap de entrega

Fases em sequência. As datas dependem do tamanho da equipe e serão definidas após a Fase 0.

| Fase | Foco | Entregas |
| :---- | :---- | :---- |
| **Fase 0 — Descoberta** | Fechar as regras de negócio | **Concluída (03/09).** Blocos 4–8 pela Yslane (28/08); Alisson fechou semanal (02/09) e cálculo da parcela + diária + dezena + mensal + troca de estrutura (03/09). Todas as regras de vencimento estão na seção 5. |
| **Fase 1 — Cadastros** | Clientes, contratos, usuários | Cadastro de clientes e de contratos/aparelhos (1 cliente → N contratos), anexos de documento, login e perfis de acesso. |
| **Fase 2 — Estruturas e agenda** | Vencimentos e "cobrar hoje" | **Implementada (04/09).** Model `Vencimento` (+ `UniqueConstraint(contrato, numero)`), recorrência das 5 estruturas (`apps/pagamentos/recorrencia.py`, com `python-dateutil`), geração via `Contrato.gerar_vencimentos()`, `data_prevista_quitacao` automática, job `manage.py gerar_vencimentos` (~60 dias à frente + `sincronizar_status` em massa), painel **"Cobrar hoje"** (`/pagamentos/cobrar-hoje/`), aviso `parcela × nº ≠ total` no cadastro e lembrete diário (`manage.py enviar_lembrete_diario`) — canal **WhatsApp** (Alisson, 04/09), envio de verdade **stub** até existir conta Business. **Falta:** virar tarefa do Django-Q2 no deploy. |
| **Fase 3 — Pagamentos** | Registro e baixa | **Implementada (03/09).** Model `Pagamento` (uma linha por parcela, `UniqueConstraint(contrato, vencimento)` + `CheckConstraint`), baixa manual (`/pagamentos/contrato/<pk>/novo/`), **pagamento parcial com transporte de saldo** para a próxima parcela (ou `Contrato.saldo_transportado`), estorno, histórico por cliente + `/pagamentos/historico/`, trilha via `django-auditlog`. **Quitação é manual** (`/contratos/<pk>/quitar/` — a baixa nunca quita). `Cobranca` movido para a Fase 6. |
| **Fase 4 — Atraso** | Juros e status | **Implementada (04/09).** Lógica pura pronta e testada (`apps/pagamentos/atraso.py`): dias de atraso com a janela da semanal, **juros de R$ 5,00/dia**, os 4 status, cor da UI e **alerta de bloqueio aos 7 dias**. Ligada ao `Contrato` (`situacao_atraso` / `status_efetivo` / `sincronizar_status`), com bloco "Situação hoje" no detalhe e coluna no admin. O cálculo usa a **parcela (`Vencimento`) em aberto mais antiga** (`parcela_em_aberto()` / `data_referencia_atraso()`) quando o contrato já tem vencimentos gerados; `proximo_vencimento` manual só entra como *fallback* antes disso. Atualização em massa do `status` salvo roda no job diário `gerar_vencimentos` (Fase 2). Lista/filtro de contratos e o painel "Cobrar hoje" usam o status calculado. Ver seção 4.6. |
| **Fase 5 — Relatórios** | Visão gerencial | Visão diária consolidada, relatórios semanais e mensais, exportação em Excel e PDF. |
| **Fase 6 — Cobrança ao cliente** | WhatsApp automático (Modalidade B) | Integração com API oficial, número comercial, configuração por cliente e mensagens de atraso. |
| **Fase 7 — Futuro** | Expansões | Módulo de motos, portal do cliente, geração de chave Pix e conciliação bancária. |

---

## 10. Pendências da entrevista

### Respondido no formulário da Yslane (28/08)

| # | Pergunta | Resposta |
| :---- | :---- | :---- |
| Q3 | Maior dificuldade | Acompanhar as cobranças diárias. |
| Q4 | Quem mais usa | Só Yslane e Alisson. |
| Q13 | Ao quitar | Marca como quitado e para de cobrar — **Sim**. |
| Q14/Q15 | Registro de pagamento | Registro individual, **vinculado à parcela** (nº + data). |
| Q16 | Pagamento parcial | **Aceito**; o saldo é somado ao próximo pagamento. |
| Q17 | Comprovante por pagamento | **Não** obrigatório. |
| Q18 | Histórico por cliente | **Sim**, completo desde o início. |
| Q19 | Canal no vencimento | **Lembrete para a Yslane** (os dois seria ótimo). |
| Q21 | Horário | **08:30**. |
| Q22 | Texto da mensagem | Yslane vai preparar e enviar. `[PENDENTE]` |
| Q23 | Número de origem | **Pessoal da Yslane**. |
| Q24 | Quem dá baixa | **Sistema**, se detectar o pagamento; senão manual. |
| Q25 | Atraso | **Continua cobrando todo dia**. |
| Q26/Q28 | Tolerância / escalonamento | **7 dias de atraso → aparelho bloqueado**. |
| Q27 | Juros | **R$ 5,00 por dia** de atraso. |
| Q29 | Status visual | **Verde / vermelho**. |
| Q30 | Visão diária | **Lista de clientes para cobrar no dia**. |
| Q31/Q32 | Relatórios / exportação | **Sim** para ambos. |
| Q33 | Onde acessa | **Maioria no celular**. |
| Q34 | Outros logins | Não. |
| Q36 | Sistema de referência | Não. |
| Q37 | Item indispensável na v1 | Organização das cobranças — não se perder com datas e dias de atraso. |

### Ainda em aberto

**Com o Alisson (bloqueiam a cobrança PIX automática — ver [`COBRANCA-PIX-CORA.md`](COBRANCA-PIX-CORA.md)):**

- Acesso à API da Cora: conta PJ, plano **CoraPro** (não é API aberta) e certificado `.PEM` + `.KEY`.
- Ainda em aberto: um QR/dia x um QR/parcela (se algum dia o juro entrar no QR);
  comportamento quando a API da Cora ou o envio automático falha.
- **Já decidido (03/09):** geração diária só da **diária** (domingo incluído; as demais
  geram na data da parcela); juro fica por fora do QR; **envio automático ao cliente,
  sem a Yslane** → puxa a Fase 6 como dependência dura; **pagamento parcial via PIX aceito**.
- Só começa depois das Fases 2, 3 e 6. Reescrita, dependências e faseamento **7a–7d** no doc.

**Com a Yslane (não bloqueiam):**

- **Texto final da mensagem** de cobrança (Q22) — a Yslane manda o dela; até lá vale o rascunho provisório da [seção 8](#8-cobrança-automática--decisão-de-canal).

**Respondido pelo Alisson (03/09) — destrava a Fase 2:**

- **Cálculo do valor da parcela** (Q10): feito **fora do sistema** (GPT "vendas dos
  celulares"). Sem fórmula no sistema — `valor_parcela` e `num_parcelas` são **manuais**.
- **Diária** (Q9): **paga todo dia, sem folga** — domingo inclusive.
- **Por dezena** (Q9): a cada **10 dias corridos** a partir da `data_inicio`
  (pegou dia 3 → paga dia 13, 23, …). Não são períodos fixos do mês.
- **Mensal** (Q9): **dia escolhido pelo cliente**, recorrente por mês (não é dia fixo
  global nem "a cada 30 dias"). Usa data/dia manual por contrato.
- **Troca de estrutura no meio do contrato** (Q11): **não ocorre.** A estrutura é
  fixa; caso precise mudar, refaz-se o contrato. Sem lógica de recálculo de saldo.

**Respondido pelo Alisson (02/09):**

- **Texto da mensagem** (Q22, provisório): usar o rascunho da seção 8 até a Yslane enviar o dela.
- **"Automático x pessoal" varia por cliente?** (Q20): **não** — configuração global, sem variação por cliente.
- **Semanal** sem dia de referência: **janela até o fim da semana** — a parcela só conta como atraso depois de domingo (atraso e juros começam na segunda seguinte).
- **Nº / identificador único de contrato** (Q7): não existe; o sistema pode gerar um nº interno, mas não é obrigatório.
- **Fiador/avalista**: não é usado — sem campo no cadastro.
- **Bloqueio do aparelho** aos 7 dias: **ação manual do vendedor**; o sistema só alerta.
- **Prazo/urgência** (Q35): **3 a 4 semanas**, podendo se estender se necessário.
- **Motos** (R3): **fora da v1** — esta versão é só celulares.

---

## 11. Riscos e mitigações

| Risco | Mitigação |
| :---- | :---- |
| ~~Regras da diária, dezena, mensal e cálculo da parcela dependem do Alisson.~~ | **Resolvido (03/09)** — regras na seção 5. A Fase 2 pode andar. Cálculo da parcela é externo: `valor_parcela` fica manual. |
| Parcela digitada errada (o sistema não valida contra uma fórmula). | `valor_parcela × num_parcelas` deve bater com o valor total do contrato — mostrar o confronto na tela de cadastro e um aviso quando divergir. |
| Baixa automática depende de "o sistema saber que o pagamento entrou" — sem integração de Pix isso não existe. | v1 com **baixa manual**; baixa automática só depois da integração de Pix (fase seguinte). Não prometer automático na v1. |
| Envio automático ao cliente pelo número **pessoal** da Yslane → bloqueio do WhatsApp. | Manter Modalidade A (lembrete para a Yslane) como base da v1. Modalidade B só com provedor oficial. |
| "Bloquear o aparelho" aos 7 dias pode ser lido como função do sistema. | Tratar como **alerta**: o sistema sinaliza, o bloqueio é ação do vendedor (confirmar com Alisson). |
| Crescimento da base e entrada das motos. | Modelar o contrato de forma genérica (produto = celular/moto) desde o início. |
| Perda de dado financeiro. | Backup diário do banco, trilha de auditoria e confirmação na baixa. |
| Dependência de uma só pessoa (Yslane). | Alisson com login e visão dos relatórios; manual de uso curto. |
| Cobrança duplicada (dor atual). | Status por parcela + registro de quem/quando deu baixa + alerta quando o pagamento já foi lançado. |
| Estrutura semanal sem dia de referência. | Janela de vencimento (ex.: fim da semana) para o sistema conseguir apontar atraso. |

---

## 12. Próximos passos imediatos

1. ~~Alisson define as regras que bloqueavam a Fase 2.~~ **Feito (03/09)** — ver seções 5 e 10.
   **Agora:** iniciar a Fase 2 (model `Vencimento` + uma estratégia por estrutura + job diário).
2. Yslane envia o **texto final da mensagem** de cobrança (até lá vale o rascunho da [seção 8](#8-cobrança-automática--decisão-de-canal)).
3. Seguir a Fase 1 (cadastros — em andamento). A **Fase 4** (juros de R$ 5/dia e status) já
   está em andamento: lógica pronta e ligada ao `Contrato`; o que falta (atualização em
   massa do `status`) depende do job diário da Fase 2. Ver [seção 4.6](#46--atraso-e-inadimplência).
4. Validar o modelo de dados da [seção 6](#6-modelo-de-dados-proposto) com um exemplo real de
   cliente em cada uma das 5 estruturas, assim que o Alisson passar as 4 regras.
5. Escolher ambiente de hospedagem.

---

## 13. Stack técnica

O back-end será feito em **Django**. As escolhas em volta priorizam **pouca infraestrutura e
manutenção por um único desenvolvedor**. Os itens marcados `[fase seguinte]` só entram depois da v1.

| Camada | Escolha | Observação / alternativa |
| :---- | :---- | :---- |
| Back-end | **Django 5.x** | Django REST Framework só se surgir necessidade de API (não no início). |
| Banco | **PostgreSQL** | SQLite no ambiente de desenvolvimento; Postgres gerenciado em produção. |
| Front-end | Django Templates + **HTMX** + **Alpine.js** + **Tailwind CSS** | Renderizado no servidor, responsivo. React + DRF seria trabalho desnecessário para este porte. |
| Formulários | django-crispy-forms + crispy-tailwind, django-widget-tweaks | Telas de cadastro e de baixa rápidas e consistentes. |
| Admin / backoffice | Django Admin + **django-unfold** + **django-import-export** | O admin já cobre boa parte do uso da Yslane. `import-export` migra a planilha atual de um `.xlsx`. |
| Tarefas agendadas | **Django-Q2** ou management command + cron do provedor | Job diário: gera vencimentos e monta a fila de cobrança, com retry no envio. Migrar para Celery + Redis só se o volume crescer. |
| Lembrete p/ Yslane (Modalidade A) | **WhatsApp** (Alisson, 04/09 — substitui a ideia de Telegram/e-mail) | Mesma conta/API da Modalidade B (Cloud API via BSP). Texto e job já prontos (`apps/pagamentos/lembrete.py`); envio real é **stub** até existir a conta Business — ver seção 9. |
| Mensagem ao cliente (Modalidade B) | **WhatsApp Cloud API** (Meta) via BSP: 360dialog ou Zenvia `[fase 6]` | Caminho oficial, sem risco de bloqueio. Exige verificação de empresa e templates aprovados — a mesma conta serve para a Modalidade A. |
| Pix na mensagem | `pix-utils` + `qrcode` para BR Code estático (chave fixa) | Pix dinâmico / conciliação automática exige um PSP: Efí, Asaas ou Mercado Pago. |
| Relatórios | **WeasyPrint** (PDF), **openpyxl** ou xlsxwriter (Excel) | WeasyPrint reaproveita templates HTML/CSS para o layout do relatório. |
| Gráficos do painel | Chart.js (no navegador) | Só se o dashboard pedir; números renderizados no servidor já resolvem muito. |
| Validação BR | `validate-docbr` (CPF), `django-phonenumber-field` + `phonenumbers`, `django-localflavor` | CPF válido e número de WhatsApp normalizado (E.164) para a API. |
| Datas / recorrência | `python-dateutil` (`relativedelta`, `rrule`) | Núcleo das 5 estruturas de pagamento — ver nota abaixo. |
| Valores monetários | `DecimalField` (somente BRL) — **nunca `float`** | django-money se quiser formatação/locale, dispensável para moeda única. |
| Auditoria | **django-auditlog** (ou django-simple-history) | "Quem deu baixa e quando" + rastro contra cobrança duplicada. |
| Autenticação | Django auth + **django-allauth** (reset de senha) | 2 usuários com perfis. django-two-factor-auth opcional (dado financeiro). |
| Configuração / segredos | `django-environ` ou `python-decouple` | Variáveis em `.env`, sem segredo no código. |
| Monitoramento de erro | **Sentry** (plano gratuito) | Recomendado para um app que movimenta cobrança. |
| Hospedagem | **Render** ou **Railway** — Gunicorn + WhiteNoise | Postgres gerenciado + cron nativo + deploy por git. PythonAnywhere se quiser algo ainda mais simples. |
| Backup | Backup do provedor + `pg_dump` noturno para Cloudflare R2 / Backblaze B2 (`django-dbbackup`) | Dado financeiro não pode depender de um único backup. |
| Testes | `pytest-django` + `model-bakery` | Cobrir a geração de vencimentos e o cálculo de atraso. |

### Notas de implementação para este projeto

- **As 5 estruturas = lógica de recorrência de datas.** Uma estratégia por estrutura
  (diária / semanal / dezena / quinzenal / mensal) usando `relativedelta` para "dia fixo do mês",
  "a cada 15/30 dias" e "a cada 10 dias". Gerar os `Vencimento` **antecipadamente**
  (ex.: próximos 60 dias) no job diário, em vez de calcular na hora.
- **Migração da planilha:** `django-import-export` lê o Excel atual e importa Clientes/Contratos
  já validando CPF e telefone. Evita redigitação.
- **Cobrança duplicada:** além do `auditlog`, usar `UniqueConstraint(contrato, vencimento)` no
  pagamento e um aviso na tela quando o vencimento já tiver baixa.
- **Lembrete diário para a Yslane:** bot do Telegram é o menor atrito para a Modalidade A; o
  WhatsApp oficial fica só para a conversa com o cliente (Modalidade B).
- **LGPD:** dados pessoais + financeiros. HTTPS obrigatório, 2FA opcional, backup cifrado e uma
  regra de retenção para os anexos (comprovantes de Pix).

---

## 14. Backlog — o que falta

Atualizado em 03/09. Fecha o gap entre o roadmap (seção 9) e o estado do código.

### Bloqueios — decisões

**Com o Alisson (travavam a Fase 2) — RESOLVIDOS (03/09):**

- [x] Cálculo do valor da parcela → **externo** (GPT "vendas dos celulares"); `valor_parcela` fica manual
- [x] Diária tem folga? → **não, todo dia** (domingo inclusive)
- [x] Por dezena → **a cada 10 dias corridos** desde a `data_inicio`
- [x] Mensal → **dia escolhido pelo cliente**, recorrente por mês (manual por contrato)
- [x] Troca de estrutura no meio do contrato → **não ocorre**; estrutura fixa, refaz o contrato se precisar

**Ainda em aberto:**

- [ ] Confirmar a fronteira "atrasado → inadimplente" (hoje inferida em 7 dias, `LIMITE_INADIMPLENTE`) — Alisson
- [x] Mensal: mesmo dia do mês da `data_inicio`, recorrente (`relativedelta(months=n)`) — Alisson (03/09, confirmado na Fase 2)
- [x] Quinzenal: a cada 15 dias corridos da `data_inicio` (`data_inicio + 15·n`) — Alisson (03/09, confirmado na Fase 2)
- [ ] Texto final da mensagem de cobrança (há rascunho provisório na [seção 8](#8-cobrança-automática--decisão-de-canal)) — Yslane
- [ ] Cobrança PIX automática via Cora — ver [`COBRANCA-PIX-CORA.md`](COBRANCA-PIX-CORA.md) (Fase 7)

### Fase 1 — Cadastros (quase completa)

- [x] `usuarios.Usuario` (perfis financeiro/dono), login/logout
- [x] `clientes.Cliente` — CRUD web + admin com import/export
- [x] `contratos.Contrato` + `DocumentoContrato` — CRUD web + anexos + admin
- [x] UI mobile-first (CSS das 5 telas)
- [x] **Modelo de acesso definido (Alisson, 02/09):** `dono` ⊇ `financeiro` — vê e faz
  tudo que o financeiro faz, e mais telas/ações exclusivas (relatórios etc.) que ainda
  serão desenhadas. Primitivo pronto: `Usuario.is_dono` / `is_financeiro` +
  `usuarios.mixins.DonoRequeridoMixin` (anônimo → login, financeiro → 403). Telas
  compartilhadas seguem só com `LoginRequiredMixin`; nada foi restringido ainda.
- [x] **Auto-revisão mobile (375px) das 5 telas + login (02/09).** Ajustes aplicados:
  (1) lista de contratos e cards do cliente passam a mostrar/filtrar o **status
  calculado** (`status_efetivo`), igual ao detalhe; (2) telefone do cliente vira
  `(83) 9XXXX-XXXX` clicável (`tel:`) + link WhatsApp (`wa.me`) nas telas de detalhe e
  listas; (3) aviso da Fase 2 no topo do form de contrato virou `<details>` recolhível
  e `.empty` com menos padding. Achados **não** resolvidos: filtro de status roda em
  memória (ok com ~25 contratos; o job diário da Fase 2 é a solução real).
- [x] **Massa de demonstração:** `manage.py seed_demo` cria 10 clientes + 10 contratos
  em situações variadas (5 estruturas; em dia / vence hoje / atrasado / inadimplente
  com alerta de bloqueio / semanal na janela / quitado / sem próximo vencimento).
  Datas relativas a hoje, idempotente, `--reset` recria. Serve de template pro
  protótipo e de massa pros testes manuais.
- [ ] Revisão final do fluxo de cadastro no celular **com a Yslane** (a auto-revisão
  não substitui a validação dela)

### Fase 2 — Estruturas e agenda (**núcleo implementado em 03/09**)

- [x] Model `Vencimento` (`apps/pagamentos/models.py`) + `UniqueConstraint(contrato, numero)`
- [x] Uma estratégia por estrutura, com `python-dateutil` (`apps/pagamentos/recorrencia.py`):
  - diária: `data_inicio + n` dias (todos os dias, sem folga)
  - semanal: `data_inicio + 7·n` dias; atraso só depois do domingo (janela em `atraso.py`)
  - dezena: `data_inicio + 10·n` dias
  - quinzenal: `data_inicio + 15·n` dias
  - mensal: `data_inicio + relativedelta(months=n)` (mesmo dia do mês; meses curtos caem no último dia)
- [x] Geração a partir de `data_inicio`, `valor_parcela` e `num_parcelas` (`Contrato.gerar_vencimentos()`)
- [x] Job que gera vencimentos ~60 dias à frente — `manage.py gerar_vencimentos` (`--dias`, `--hoje`); vira tarefa do `Django-Q2` no deploy
- [x] Cálculo automático da `data_prevista_quitacao` (`Contrato.atualizar_data_prevista_quitacao()`)
- [x] Aviso no cadastro quando `valor_parcela × num_parcelas` não bate com `valor_total` (`Contrato.parcelas_conferem`)
- [x] Painel **"Cobrar hoje"** (`/cobrar-hoje/`, `apps/pagamentos/views.py`)
- [x] Job chamando `Contrato.sincronizar_status()` em massa (dentro de `gerar_vencimentos`)
- [x] Sem lógica de troca de estrutura / recálculo (Alisson, 03/09: não ocorre)
- [x] Lembrete diário para a Yslane — canal definido: **WhatsApp** (Alisson, 04/09).
  `manage.py enviar_lembrete_diario` monta a agenda + o texto (`apps/pagamentos/agenda.py`,
  `apps/pagamentos/lembrete.py`); `enviar()` é **stub** (só loga) até existir conta WhatsApp
  Business Cloud API — decisão explícita do Alisson ("deixar pronto, sem conta ainda").
- [x] Ligar `proximo_vencimento` à parcela `Vencimento` em aberto — Fase 4 (04/09)
- [x] Testes (`apps/pagamentos/test_vencimentos.py`, `test_lembrete.py`) — 151 passando no total

### Fase 3 — Pagamentos (**implementada em 03/09**)

- [x] Model `Pagamento` (`apps/pagamentos/models.py`) — `contrato · vencimento? ·
  data_pagamento · valor_pago · forma · usuario_baixa · comprovante? · observacao`
- [x] Lançamento vinculado à parcela (nº + data) — `PagamentoCreateView`
  (`/pagamentos/contrato/<pk>/novo/`), parcela em aberto pré-selecionada
- [x] Baixa manual + **pagamento parcial**: a parcela vira `parcial` e o saldo
  entra no `valor_previsto` da próxima parcela em aberto (pagamento a maior
  cascateia como crédito); sem parcela seguinte, vai para `Contrato.saldo_transportado`
  (drenado por `gerar_vencimentos`). Decisão do Alisson (03/09): "uma linha por
  parcela + carrega saldo" — resolve a contradição §6/§14 × Q16 mantendo a
  `UniqueConstraint(contrato, vencimento)`
- [x] Anti cobrança duplicada: `UniqueConstraint(contrato, vencimento)` +
  `CheckConstraint(valor_pago > 0)` + checagem no `PagamentoForm`
- [x] Estorno (`PagamentoEstornarView`, POST) — reverte a parcela; o transporte
  para parcelas seguintes **não** é revertido (a view avisa p/ conferência manual)
- [x] Histórico completo por cliente (`clientes/detalhe.html`) + `/pagamentos/historico/`
- [x] Trilha de auditoria: `django-auditlog` em `Cliente`, `Contrato`,
  `DocumentoContrato`, `Vencimento`, `Pagamento` + `AuditlogMiddleware`
- [x] Quitação **manual** (Alisson, 03/09: a baixa nunca quita) —
  `ContratoQuitarView` (`/contratos/<pk>/quitar/`, POST) marca `quitado` +
  recalcula `data_prevista_quitacao`; botão no detalhe quando todas as parcelas pagas
- [x] Testes — `apps/pagamentos/test_pagamentos.py` (20); 136 no total
- Adiado: `Cobranca` (Fase 6, junto do envio de mensagem)

### Fase 4 — Atraso (implementada em 04/09)

- [x] Lógica pura (`apps/pagamentos/atraso.py`) + testes
- [x] Ligação ao `Contrato` (`situacao_atraso`, `status_efetivo`, `sincronizar_status`)
- [x] Bloco "Situação hoje" no detalhe + coluna "atraso hoje" no admin
- [x] Atualização em massa do `status` salvo (job diário `gerar_vencimentos` da Fase 2)
- [x] Cálculo por **parcela específica**: `parcela_em_aberto()` / `data_referencia_atraso()`
  usam o `Vencimento` em aberto mais antigo; `proximo_vencimento` manual vira *fallback*
  só quando o contrato ainda não tem vencimentos gerados
- [x] Status calculado na **lista/filtro** de contratos e nos cards do cliente
- Em aberto: confirmar com o Alisson a fronteira "atrasado → inadimplente"
  (`LIMITE_INADIMPLENTE`, hoje inferida nos mesmos 7 dias do gatilho de bloqueio)

### Fase 5 — Relatórios (não iniciada)

- [ ] Visão diária consolidada (previsto, recebido, atrasados)
- [ ] Relatórios semanal e mensal
- [ ] Exportação em Excel (`openpyxl`) e PDF (`WeasyPrint`)

### Fase 6 — Cobrança direto ao cliente (não iniciada)

- [ ] Model `Cobranca` (notificação — ver seção 6): `contrato · data_alvo ·
  canal · status · mensagem · enviado_em`. Movido da Fase 3 — só faz sentido
  junto do envio de mensagem
- [ ] Integração WhatsApp com provedor oficial (Cloud API)
- [ ] Mensagens automáticas de vencimento e atraso

### Fase 7 — Futuro

- [ ] Módulo de motos
- [ ] Portal do cliente
- [ ] **Cobrança PIX automática via API da Cora** — ciclo diário
  gerar → enviar → conciliar → sinalizar **pago / não pago** (badge ✅/❌ +
  lista "entrar em contato" para a Yslane). Especificação, bloqueios, perguntas
  para o Alisson e faseamento **7a–7d** em
  [`COBRANCA-PIX-CORA.md`](COBRANCA-PIX-CORA.md). Depende das Fases 2, 3 e 6.

### Técnico / infra (transversal)

- [ ] Migrar para **PostgreSQL** em produção (hoje SQLite)
- [ ] `django-unfold` no admin (planejado, ainda não instalado)
- [ ] Configurar **Sentry**
- [ ] Deploy (Render ou Railway — Gunicorn + WhiteNoise)
- [ ] Backup diário do banco
- [x] `python-dateutil` no `requirements.txt` (Fase 2) · [x] `django-auditlog` (Fase 3) · [ ] `Django-Q2` (deploy)
