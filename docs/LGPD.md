# LGPD — privacidade, retenção e pedidos do titular

Este sistema guarda **dados pessoais e financeiros** de clientes (nome, CPF,
telefone, contratos, parcelas, pagamentos e anexos). Isso o coloca sob a
**Lei 13.709/2018 (LGPD)**. Este documento reúne o mínimo para operar em
conformidade: o aviso de privacidade para entregar ao cliente, a regra de
retenção dos anexos e o passo a passo para atender um pedido do titular.

> Campos entre `[COLCHETES]` só você pode preencher — dados da empresa e do
> responsável. Preencha antes de usar o aviso com clientes.

---

## 1. Papéis

| Papel LGPD | Quem | Responsabilidade |
|---|---|---|
| **Controlador** | `[RAZÃO SOCIAL / NOME]` — CNPJ/CPF `[..]` | decide o que é coletado e por quê |
| **Encarregado (DPO)** | `[NOME]` — `[E-MAIL/telefone de contato]` | canal do titular e da ANPD |
| **Operadores** | Render (hospedagem), Evolution API (envio de WhatsApp), Cora (Pix) | tratam dados a mando do controlador |

O sistema é de uso interno de **duas pessoas** (Yslane — financeiro; Alisson —
dono). Não há acesso de terceiros nem venda/compartilhamento de dados para fins
de marketing.

---

## 2. Aviso de privacidade (entregar ao cliente)

> Texto sugerido. Pode ir impresso junto do contrato, por mensagem no primeiro
> contato, ou como anexo. Ajuste os `[COLCHETES]`.

---

**Aviso de Privacidade — `[NOME DA EMPRESA]`**

Para vender aparelhos a prazo e acompanhar os pagamentos, tratamos alguns dados
seus:

- **Quais dados:** nome, CPF, telefone/WhatsApp; e os dados do contrato
  (valor, parcelas, vencimentos, pagamentos, comprovantes e documentos que você
  nos enviar).
- **Para quê:** cadastrar e executar o contrato de venda a prazo; emitir e
  conferir cobranças (inclusive Pix); lembrar vencimentos e cobrar parcelas em
  atraso; cumprir obrigações legais e fiscais; e defender nossos direitos em
  caso de inadimplência.
- **Base legal:** execução de contrato (art. 7º, V), cumprimento de obrigação
  legal/regulatória (art. 7º, II) e legítimo interesse na cobrança de valores
  devidos (art. 7º, IX).
- **Com quem compartilhamos:** empresa de hospedagem do sistema; provedor de
  envio de mensagens de WhatsApp; e a instituição de pagamento responsável pelo
  Pix. Não vendemos nem cedemos seus dados para publicidade de terceiros.
- **Por quanto tempo:** enquanto o contrato estiver ativo e pelo prazo em que a
  cobrança e a defesa de direitos ainda forem possíveis (em regra, até 5 anos
  após a quitação ou o encerramento). Comprovantes e documentos podem ser
  guardados por esse mesmo período.
- **Seus direitos:** confirmar o tratamento, acessar, corrigir, pedir
  anonimização, portabilidade ou exclusão dos dados que não precisamos mais
  manter por lei. Fale com nosso encarregado: **`[E-MAIL / telefone]`**.
- **Reclamações:** você também pode procurar a ANPD (gov.br/anpd).

---

## 3. Retenção dos anexos (comprovantes e documentos)

**Decisão (09/09/2026): não há expurgo automático.** Os arquivos de
`Pagamento.comprovante` e `DocumentoContrato.arquivo` ficam guardados enquanto
forem úteis para o contrato e para a defesa de direitos. Nada é apagado por
rotina/cron.

Regra prática:

- **Contrato ativo ou em atraso:** manter tudo.
- **Contrato quitado há mais de 5 anos:** os anexos já podem ser removidos —
  fazer isso em **revisão manual**, quando sobrar tempo, ou sempre que o titular
  pedir (seção 4). 5 anos cobre o prazo geral de cobrança de dívidas
  (Código Civil, art. 206) e a guarda fiscal usual.
- **Ao remover:** apague o arquivo pela tela do contrato/pagamento ou pelo
  admin. O registro de `Pagamento` / `DocumentoContrato` pode continuar (valor,
  data, forma) — o que sai é só o arquivo. A trilha do `django-auditlog`
  registra a remoção.

Se um dia quiser automatizar, o ponto natural é um novo comando
`manage.py expurgar_anexos --anos 5` chamado pela `rotina_diaria`. Fora de
escopo por ora.

---

## 4. Pedido do titular (acesso / correção / exclusão / portabilidade)

Prazo de resposta: **até 15 dias** do pedido (LGPD art. 19, §2º). Registre a data.

### Passo a passo

1. **Receber e registrar.** Anote quem pediu, quando, por qual canal e o que
   quer (acesso, correção, exclusão, portabilidade, anonimização). Guarde a
   mensagem.
2. **Confirmar a identidade.** Só atenda o próprio titular (ou representante com
   procuração). Confira nome + CPF contra o cadastro. Nunca mande dados pessoais
   para um contato não confirmado.
3. **Localizar os dados.** No admin ou no site, abra o `Cliente` e os
   `Contrato`s dele — de lá se chega a `Vencimento`, `Pagamento`,
   `DocumentoContrato` e aos anexos. Há também o histórico do `django-auditlog`.
4. **Executar conforme o pedido:**

   | Pedido | O que fazer |
   |---|---|
   | **Acesso / portabilidade** | Exportar os dados do cliente e dos contratos (admin → *export*, ou relatório) e entregar em PDF/CSV ao titular confirmado. |
   | **Correção** | Editar o cadastro pela tela de cliente/contrato. O auditlog guarda o antes/depois. |
   | **Exclusão** | Ver a regra abaixo — nem tudo pode ser apagado de imediato. |
   | **Anonimização** | Alternativa à exclusão quando ainda há obrigação de guarda: substituir nome por algo como `Cliente 000123`, zerar telefone, manter CPF só se exigido pela cobrança. |

5. **Responder ao titular** por escrito, dizendo o que foi feito e — se algo foi
   mantido — a base legal (obrigação legal / defesa de direitos). Guarde a
   resposta junto do pedido.

### O que pode ser apagado e o que deve ser retido

- **Pode apagar já:** anexos (comprovantes/documentos) de contratos **quitados**;
  telefone/observações que não são mais necessários; cadastro de cliente **sem
  nenhum contrato**.
- **Reter enquanto durar a obrigação (não apagar a pedido):** dados de contratos
  **ativos ou em atraso**; registros mínimos de pagamento (valor, data, forma) e
  do contrato necessários para cobrança, comprovação fiscal e defesa em juízo,
  em regra por **até 5 anos** após a quitação. Nesse caso, ofereça
  **anonimização** e explique o motivo da retenção.
- **Trilha de auditoria (`auditlog`):** manter — é registro de conformidade, não
  finalidade de marketing.

### Como excluir no sistema

- **Anexo isolado:** botão de remover na tela do pagamento/documento, ou pelo
  admin.
- **Cliente + tudo ligado a ele:** admin → `Cliente` → *Delete* (o cascade
  remove contratos, vencimentos e pagamentos). **Confira antes** que não há
  obrigação de retenção pendente. Alternativa mais segura: anonimizar em vez de
  deletar.
- **Pelo Shell do Render**, para casos maiores, com um `python manage.py shell`
  e o ORM — sempre depois de um backup do banco.

---

## 5. Medidas de segurança já aplicadas (art. 46)

- HTTPS obrigatório (HSTS), cookies `Secure`/`SameSite`, redirect para HTTPS.
- Acesso restrito a 2 contas; senha mínima de 12 caracteres; lockout de
  força-bruta (`django-axes`); sessão expira em 12 h.
- Anexos entregues só por view autenticada, sempre como download, com CSP
  `default-src 'none'`; sem URL pública de mídia.
- Upload validado (só pdf/jpg/png/webp, até 10 MB).
- Trilha de auditoria de quem alterou o quê (`django-auditlog`).
- Segredos fora do Git; `SECRET_KEY` gerada pelo provedor.

**Pendências de infra que afetam LGPD** (ver
[`SEGURANCA-OPERACIONAL.md`](SEGURANCA-OPERACIONAL.md)): disco persistente para
os anexos, banco com backup (o plano free do Postgres não tem) e um backup
off-site cifrado.
