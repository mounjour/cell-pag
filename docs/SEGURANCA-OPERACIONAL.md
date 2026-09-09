# Segurança operacional — o que só você (Alisson) faz

O trabalho de segurança **em código** está feito e documentado em
[`SEGURANCA.md`](SEGURANCA.md) (17 itens da branch `seguranca/hardening-revisao`).

O que sobra são **cliques em painel e decisões suas** — nada disso o Claude Code
consegue fazer. Este guia é o passo a passo, em ordem de prioridade, com *onde
clicar* e *como conferir que deu certo*.

Repositório: `github.com/mounjour/cell-pag` · Site: `https://cell-pag.onrender.com`

Legenda: ⬜ a fazer · ✅ feito · ⏸️ adiado de propósito

---

## A. GitHub — Settings › Code security

Abra: **github.com/mounjour/cell-pag → Settings → Code security** (menu da
esquerda; em repositório pessoal pode aparecer como *"Code security and analysis"*).

### A1. ⬜ Dependabot — alerts + security updates

O arquivo [`.github/dependabot.yml`](../.github/dependabot.yml) já está no repo
(varredura `pip` + `github-actions` semanal). Falta **ligar** na conta:

1. Em *Code security*, seção **Dependabot**.
2. Ligue **Dependabot alerts**.
3. Ligue **Dependabot security updates** (abre PR sozinho quando sai correção).
4. *(opcional)* **Dependabot version updates** — como o `.yml` já existe, aqui
   só confirma que ele foi detectado ("Config file: `.github/dependabot.yml`").

**Conferir:** aba **Security → Dependabot** do repo lista "no open alerts" ou os
alertas encontrados. Em alguns dias deve aparecer o primeiro PR do bot em
**Pull requests**.

### A2. ⬜ Secret scanning + push protection

1. Mesma tela, seção **Secret scanning**. Clique **Enable**.
2. Ligue **Push protection** (bloqueia o `git push` que carrega token/chave).

> Repositório **privado** exige GitHub Advanced Security (planos pagos). Se o
> botão estiver bloqueado: ou deixe o repo público, ou apenas garanta a
> disciplina de segredo em `.env` (já coberta pelo `.gitignore`). Registre a
> escolha aqui.

**Conferir:** faça um teste local — crie um arquivo com uma linha tipo
`AWS_SECRET_ACCESS_KEY=AKIA...EXEMPLO` e tente `git push` numa branch de teste;
com push protection ligado o push é recusado. Apague a branch depois.

### A3. ⬜ Branch protection na `main`

**Settings → Branches → Add branch ruleset** (ou *Add rule* no formato antigo).
Alvo: `main`. Marque:

- **Require a pull request before merging** (pode deixar *Required approvals: 0*
  — você trabalha sozinho; o ganho é não commitar direto na `main`).
- **Require status checks to pass** → adicione o check do CI **quando ele
  existir** (hoje não há workflow; volte aqui depois de criar um).
- **Block force pushes** (bloqueia `git push --force` na `main`).
- **Restrict deletions**.
- *Não* marque "Do not allow bypassing" se quiser poder fazer um hotfix direto —
  mas o padrão recomendado é deixar marcado e sempre passar por PR.

**Conferir:** tente `git push --force origin main` de um branch local — deve ser
recusado. Um commit direto na `main` sem PR também.

---

## B. Render — infraestrutura

Painel: **dashboard.render.com** → serviço `cell-pag`.

### B1. ⬜ Disco persistente montado em `MEDIA_ROOT`

Sem isso, **todo comprovante e documento some a cada deploy** (o container é
efêmero). A validação e a entrega autenticada dos anexos já estão no código —
falta só o disco.

1. Serviço **web `cell-pag`** → aba **Disks** → **Add Disk**.
2. *Name:* `media` · *Mount Path:* `/opt/render/project/src/media` ·
   *Size:* 1 GB (dá para crescer depois).
3. Save — o serviço reinicia.
4. O **cron `cell-pag-rotina-diaria`** não precisa de disco (não grava anexo).

> Um disco persistente **fixa o serviço em uma instância só** (sem escala
> horizontal) — o que é perfeito para este porte.

**Conferir:** suba um comprovante por uma tela de pagamento, force um deploy
(*Manual Deploy → Clear build cache & deploy*) e confirme que o arquivo ainda
abre.

### B2. ⬜ PostgreSQL pago

O plano **free do Postgres expira em 30 dias e não tem backup** — inaceitável
para registro financeiro.

1. Banco **`cell-pag-db`** → **Settings** → **Change Plan** → **Basic** (~US$ 7/mês).
2. Confirme que **Point-in-Time Recovery / daily backups** aparece como incluso
   no plano novo.
3. Ajuste o `render.yaml` para refletir (`plan: basic-256mb`) no próximo commit —
   só para o Blueprint não voltar o plano em um redeploy.

**Conferir:** aba **Backups** ou **Recovery** do banco mostra backups sendo
gerados.

### B3. ⬜ Backup off-site do banco  ⏸️ *(decisão adiada — 09/09/2026)*

O backup do Render mitiga falha do Render, não "conta suspensa / região caiu".
O ideal é um `pg_dump` cifrado indo para um bucket S3-compatível (Backblaze B2,
Cloudflare R2). **Adiado por decisão sua** — quando quiser, o caminho é um
`scripts/backup_db.py` + uma entrada `cron` no `render.yaml`. Deixado registrado
para não se perder.

Enquanto isso: 1x por mês, pelo **Shell** do serviço web, rode
`pg_dump "$DATABASE_URL" | gzip > /tmp/cellpag-$(date +%F).sql.gz` e baixe o
arquivo pela própria aba Shell (ícone de download). Guarde fora do Render.

### B4. ⬜ Restringir quem acessa o painel do Render

Quem entra no painel lê **logs de erro, variáveis de ambiente e o banco**.

1. **Account Settings → Team / Members** (ou o *workspace*): confirme que só você
   é membro. Remova convidados antigos.
2. Ligue **2FA** na sua conta Render (**Account Settings → Two-Factor Auth**).
3. Se um dia adicionar alguém, use o menor papel possível (*Viewer*), não *Admin*.

**Conferir:** a lista de membros tem só você; seu login exige o código 2FA.

### B5. ⏸️ Variáveis das integrações (Evolution / Cora)

Só quando for ligar os canais. Passo a passo completo já está em
[`DEPLOY.md`](DEPLOY.md) §3 e §7, [`WHATSAPP.md`](WHATSAPP.md) e
[`CORA.md`](CORA.md). Resumo do que **não** pode passar batido:

- Preencher `EVOLUTION_API_URL/_API_KEY/_INSTANCE` e `CORA_CLIENT_ID/_TOKEN_URL/
  _API_BASE_URL` no grupo `cell-pag-config`.
- Confirmar que `EVOLUTION_WEBHOOK_TOKEN` e `CORA_WEBHOOK_TOKEN` **têm valor**
  (o `render.yaml` gera o da Cora; o da Evolution você define).
- Cadastrar as URLs de webhook **com `?token=<valor>` no fim** — sem o token o
  webhook é recusado (menos em `DEBUG=True`).
- Certificado/chave da Cora como **Secret Files** no web **e** no cron
  (`/etc/secrets/…`), com `CORA_CERT_PATH`/`CORA_KEY_PATH` apontando para eles.
- Depois de trocar cada `*_PROVIDER`, rodar `python manage.py rotina_diaria
  --sem-cobrancas` uma vez antes de deixar automático.

---

## C. Contas e operação

### C1. ⬜ Senha forte (12+) para os 2 usuários reais

O validador já **exige 12 caracteres na próxima troca de senha**. Force a troca:

1. Shell do serviço web → `python manage.py changepassword yslane`
   (e de novo para o usuário do Alisson).
2. Use senha longa e única (gerador do navegador / gerenciador de senhas).

**Conferir:** tentar `changepassword` com uma senha de 8 caracteres deve ser
recusado pelo validador.

### C2. ⬜ Apagar superusuário de teste em produção

Qualquer conta tipo `admin` criada para teste é porta de entrada.

```bash
# Shell do serviço web
python manage.py shell -c "from django.contrib.auth import get_user_model as g; \
print(list(g().objects.values_list('username','is_superuser','is_active')))"
```

Se aparecer `admin` (ou outra conta que não seja a da Yslane / do Alisson):

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model as g; \
g().objects.filter(username='admin').delete()"
```

**Conferir:** rode o primeiro comando de novo — só devem sobrar as 2 contas
reais. (O superusuário local de dev `admin` existe **só** no `db.sqlite3` da sua
máquina — não vai para produção.)

### C3. ✅ Saber destravar um login bloqueado

Já documentado. Quando a Yslane (ou você) errar a senha 8×, o acesso trava por
1 h e aparece a página **"Muitas tentativas"**. Para liberar na hora:

```bash
# Shell do serviço web
python manage.py axes_reset_username <usuário>
```

`python manage.py axes_reset` zera tudo; `axes_reset_ip <ip>` zera um IP.

### C4. ⬜ Conferir no log de deploy que as migrações rodaram

O `preDeployCommand` do `render.yaml` roda `python manage.py migrate` antes de
trocar a versão no ar. No deploy de segurança, confirme no **log do deploy**
(aba *Events* / *Logs* do serviço web) as linhas:

- `Applying axes.0001_initial… OK` (e as demais do `axes`)
- `Applying pagamentos.0006_alter_pagamento_comprovante… OK`
- `Applying contratos.0008_alter_documentocontrato_arquivo… OK`

Se o deploy foi anterior a essas migrações, um **Manual Deploy** as aplica.

**Conferir:** Shell → `python manage.py migrate --check` sai sem pendências
(código 0).

### C5. ⬜ LGPD — aviso, retenção e pedido do titular

Ver [`LGPD.md`](LGPD.md). Ações suas:

- Preencher os `[COLCHETES]` (razão social, encarregado, contato) no aviso de
  privacidade e passar a entregá-lo aos clientes novos.
- Ciente da regra de retenção dos anexos (**sem expurgo automático** — revisão
  manual após 5 anos da quitação).
- Guardar o procedimento de pedido do titular à mão (prazo de resposta: 15 dias).

---

## D. Saúde do projeto (recomendado, não bloqueia)

- **CI:** um workflow que roda `pytest` + `manage.py check --deploy` +
  `pip-audit` em cada PR. Depois de criado, ligar como *required status check*
  em A3.
- **Sentry** (plano free): captura de erro em produção — hoje um 500 só aparece
  se você abrir o log do Render na hora.
- **Heartbeat da `rotina_diaria`:** o cron free pode falhar calado. Um ping para
  healthchecks.io no fim da rotina avisa quando um dia **não** rodou.

---

## Checklist rápido

```
GitHub
  [ ] A1  Dependabot alerts + security updates ligados
  [ ] A2  Secret scanning + push protection ligados (ou escolha registrada)
  [ ] A3  Branch protection na main (PR + block force push)
Render
  [ ] B1  Disco persistente em /opt/render/project/src/media
  [ ] B2  Postgres no plano Basic (com backup)
  [ ] B3  Backup off-site  — adiado, registrado
  [ ] B4  Só você no time do Render + 2FA
  [ ] B5  Vars/webhooks das integrações — quando ligar os canais
Contas
  [ ] C1  Senha 12+ trocada para os 2 usuários
  [ ] C2  Superusuário de teste apagado em produção
  [x] C3  Sei rodar axes_reset_username
  [ ] C4  Migrações axes / pagamentos.0006 / contratos.0008 confirmadas no log
  [ ] C5  LGPD.md preenchido e aviso em uso
```
