# Segurança operacional — o que só você (Alisson) faz

O trabalho de segurança **em código** está feito e documentado em
[`SEGURANCA.md`](SEGURANCA.md) (17 itens da branch `seguranca/hardening-revisao`).

O que sobra são **cliques em painel e decisões suas** — nada disso o Claude Code
consegue fazer. Este guia é o passo a passo, em ordem de prioridade, com *onde
clicar* e *como conferir que deu certo*.

Repositório: `github.com/mounjour/cell-pag` · Site: `https://celulares-pag.duckdns.org`

> **Atualizado em 29/09/2026.** A hospedagem migrou do Render para uma VPS da
> KingHost com Coolify (ver [`DEPLOY-VPS.md`](../deploy/DEPLOY-VPS.md)) — a seção B
> abaixo já reflete isso. As seções A, C e D continuam valendo como estavam.

Legenda: ⬜ a fazer · ✅ feito · ⏸️ adiado de propósito

---

## A. GitHub — Settings › Advanced Security

Abra direto: **https://github.com/mounjour/cell-pag/settings/security_analysis**
(caminho pelo menu: *Settings* → seção **Security** → **Advanced Security**;
dependendo da conta aparece como "Code security" ou "Code security and analysis").
Um resumo do estado de tudo fica em
**https://github.com/mounjour/cell-pag/security** (*Security and quality → Overview*).

> Nos botões dessa tela, o texto diz o que o clique **vai fazer**: `Disable`
> visível = o recurso **já está ligado** (não clique); `Enable` = está desligado.

### A1. ✅ Dependabot — alerts + security updates  *(já ligado — conferido 09/09/2026)*

O arquivo [`.github/dependabot.yml`](../../.github/dependabot.yml) já está no repo
(varredura `pip` + `github-actions` semanal). Na tela **Advanced Security**,
seção **Dependabot**, já aparecem com `Disable` (ou seja, ligados):

- **Dependabot alerts** ✅
- **Dependabot security updates** ✅ (abre PR sozinho quando sai correção)
- **Dependency graph** ✅ (pré-requisito, também já ligado)

*(opcional)* **Dependabot malware alerts** — está com `Enable`; pode ligar.
*(opcional)* Mais abaixo, **Dependabot version updates** deve mostrar
"Config file: `.github/dependabot.yml`" detectado.

**Conferir:** **Security → Dependabot** lista "no open alerts" ou os alertas
encontrados; em alguns dias aparece o primeiro PR do bot em **Pull requests**.

### A2. ✅ Secret scanning + push protection  *(ligado — conferido 09/09/2026)*

Na Overview, **Secret scanning alerts • Enabled** ✅ e, na página
**Advanced Security** → seção **Secret scanning**, o **Push protection** está
ligado (bloqueia o `git push` que carrega token/chave).

**Conferir:** numa branch de teste, faça um commit com uma linha tipo
`AWS_SECRET_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE` e tente `git push` — deve ser
recusado. Apague a branch depois.

### A3. ✅ Branch protection na `main`  *(ruleset criado e testado — 10/09/2026)*

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

## B. VPS KingHost + Coolify — infraestrutura

Painel: Coolify no endereço interno da VPS (acesso por SSH + o painel web do
Coolify). Passo a passo completo de como tudo foi montado:
[`DEPLOY-VPS.md`](../deploy/DEPLOY-VPS.md).

> **Domínio:** hoje é `celulares-pag.duckdns.org` (DuckDNS, gratuito). Domínio
> próprio é melhor a longo prazo — a URL do webhook da Cora e da Evolution
> ficam gravadas nesses serviços, e trocar de domínio exige recadastrar as
> duas. Enquanto for o DuckDNS, o **HSTS fica em 1 dia**, sem preload (item 10
> do `SEGURANCA.md`) — subir para 1 ano/preload só quando o domínio for
> definitivo.

### B1. ✅ Disco persistente para os anexos

A VPS não é efêmera como o Render free: os anexos (`MEDIA_ROOT`) ficam num
volume do próprio container, persistente entre deploys. Sem ação pendente.

**Conferir:** suba um comprovante por uma tela de pagamento, force um novo
deploy (push na `main`) e confirme que o arquivo ainda abre depois.

### B2. ✅ Backup do PostgreSQL  *(configurado e testado — 28/09/2026)*

O Postgres é gerenciado pelo próprio Coolify (`celulares-db`). Configurado:

- **Storage:** Backblaze B2 (bucket `celulares-pag-backup-db`), cadastrado em
  Coolify como S3 Storage, com uma chave de aplicação restrita a esse bucket
  (não a master key da conta).
- **Agendamento:** backup diário (`@daily`), retenção de 14 cópias no
  Backblaze e 3 localmente na VPS.
- **Testado:** rodei um backup manual em 28/09/2026 e terminou com
  `status: success` — o arquivo `.dmp` chegou ao bucket.

Isso também resolve o antigo "backup off-site": o Backblaze já é fora da VPS,
então uma falha do servidor não leva o backup junto.

**Conferir:** Coolify → banco `celulares-db` → aba **Backups** → a lista de
execuções mostra `success` nos últimos dias. Pelo painel do Backblaze
(**Buckets → celulares-pag-backup-db → Browse Files**) os arquivos `.dmp`
aparecem e crescem em número dia a dia.

### B3. ✅ Restringir quem acessa o servidor

Acesso à VPS é só por **SSH com chave** (sem senha) como root, e o painel do
Coolify roda só na própria VPS. Não há outro usuário/convidado com acesso.

**Conferir:** tentar `ssh` com senha na VPS deve ser recusado; só a chave
autorizada entra.

### B4. ✅ Variáveis das integrações (Evolution / Cora)

**Já ligadas de verdade em produção** desde 28/09/2026
(`CORA_PROVIDER=cora`, `WHATSAPP_PROVIDER=evolution`). Passo a passo de como
foi feito (para recriar um certificado ou um webhook): 
[`CHECKLIST-ATIVACAO.md`](../integracoes/CHECKLIST-ATIVACAO.md) (registro histórico),
[`WHATSAPP.md`](../integracoes/WHATSAPP.md) e [`CORA.md`](../integracoes/CORA.md). No Coolify, os
certificados da Cora entram como variável de ambiente (não como "Secret
Files" — isso era coisa do Render), apontadas por `CORA_CERT_PATH`/
`CORA_KEY_PATH`.

**Conferir:** `/pagamentos/pix/` mostra cobranças reais da Cora; o painel
`/pagamentos/cobrar-hoje/` reflete mensagens realmente enviadas pela Evolution.

---

## C. Contas e operação

### C1. ⬜ Senha forte para os usuários reais

O validador **exige no mínimo 8 caracteres** (mais os checks de senha comum,
só-números e parecida com o usuário) — o mínimo voltou de 12 para 8 por decisão
do Alisson (PR #10 / `SEGURANCA.md` item 13). **8 é o piso, não a meta:** use
uma senha longa (12+) e única, de gerador. Usuários hoje em produção: `Yslane`
(financeiro) e `IsaqueSant` (dono/superusuário — recriado em 29/09/2026 com
senha temporária; **trocar assim que entrar**, pelo formulário de alterar
senha ou por `changepassword` no shell da produção).

```bash
python manage.py changepassword <usuario>
```

**Conferir:** `changepassword` com `12345678` deve ser recusado (senha comum /
só números); uma senha curta de 7 caracteres também.

### C2. ✅ Sem superusuário de teste em produção  *(confirmado — 29/09/2026)*

```bash
python manage.py shell -c "from django.contrib.auth import get_user_model as g; \
print(list(g().objects.values_list('username','is_superuser','is_active')))"
```

Hoje só existem `Yslane` (não-superusuário) e `IsaqueSant` (superusuário,
dono do sistema). Nenhuma conta tipo `admin`/teste. Repita o comando acima
sempre que criar ou remover um usuário, para confirmar que a lista continua só
com contas reais.

### C3. ✅ Saber destravar um login bloqueado

Já documentado. Quando a Yslane (ou você) errar a senha 8×, o acesso trava por
1 h e aparece a página **"Muitas tentativas"**. Para liberar na hora:

```bash
# Shell do serviço web
python manage.py axes_reset_username <usuário>
```

`python manage.py axes_reset` zera tudo; `axes_reset_ip <ip>` zera um IP.

### C4. ⬜ Conferir que as migrações rodaram no deploy

O `deploy/entrypoint.sh` roda `python manage.py migrate` antes de subir o site
(ver [`DEPLOY-VPS.md`](../deploy/DEPLOY-VPS.md)). Depois de um deploy, confirme no log
do container (Coolify → aplicação → **Logs**) que o `migrate` rodou sem erro.

**Conferir:** shell do container em produção → `python manage.py migrate
--check` sai sem pendências (código 0).

### C5. ✅ LGPD — aviso, retenção e pedido do titular  *(preenchido — 29/09/2026)*

Ver [`LGPD.md`](LGPD.md) — controlador, encarregado e contato preenchidos
(falta só o CPF do controlador, decisão do Alisson de deixar em branco por
ora). Ações que continuam suas:

- Passar a entregar o aviso de privacidade aos clientes novos (impresso,
  WhatsApp ou anexo — como preferir).
- Ciente da regra de retenção dos anexos (**sem expurgo automático** — revisão
  manual após 5 anos da quitação).
- Guardar o procedimento de pedido do titular à mão (prazo de resposta: 15 dias).

---

## D. Saúde do projeto (recomendado, não bloqueia)

- **CI:** o workflow (`.github/workflows/ci.yml`) já roda `pytest` +
  `manage.py check` em cada PR. Ainda falta `manage.py check --deploy` (pega
  regressão de configuração de segurança) e `pip-audit` (dependência com CVE
  conhecida) — ⬜ pendente.
- **Sentry** (plano free): captura de erro em produção — hoje um 500 só
  aparece se alguém abrir o log do Coolify na hora. ⬜ pendente.
- **Heartbeat da `rotina_diaria`:** ✅ feito em 29/09/2026 — a rotina avisa um
  check do healthchecks.io em sucesso e falha, via `ROTINA_HEALTHCHECK_URL`
  (ver [`DEPLOY-VPS.md`](../deploy/DEPLOY-VPS.md)). Falta só cadastrar a URL do check no
  Coolify (variável de ambiente) se ainda não foi feito.

---

## Checklist rápido

```
GitHub
  [x] A1  Dependabot alerts + security updates ligados
  [x] A2  Secret scanning + push protection ligados
  [x] A3  Branch protection na main (PR + block force push)
VPS KingHost + Coolify
  [x] B1  Disco persistente para os anexos (padrão do Coolify)
  [x] B2  Backup diário do Postgres para o Backblaze B2 — testado 28/09/2026
  [x] B3  Só acesso por SSH com chave; painel do Coolify só na própria VPS
  [x] B4  Evolution + Cora ligados de verdade em produção — 28/09/2026
Contas
  [ ] C1  Senha longa e única para os usuários reais (trocar a temporária do IsaqueSant)
  [x] C2  Sem superusuário de teste em produção — confirmado 29/09/2026
  [x] C3  Sei rodar axes_reset_username
  [ ] C4  Migrações confirmadas no log do deploy mais recente
  [x] C5  LGPD.md preenchido e aviso pronto para uso — 29/09/2026
Saúde do projeto
  [x] D1  Heartbeat da rotina diária (healthchecks.io) — 29/09/2026
  [ ] D2  CI com manage.py check --deploy + pip-audit
  [ ] D3  Sentry (ou equivalente) para erro 500 em produção
```
