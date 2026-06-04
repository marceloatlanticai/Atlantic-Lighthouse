# Countercurrent.ai — Deploy no GitHub + Streamlit Cloud

## Estrutura de arquivos necessária

```
countercurrent/
├── app.py
├── ingestion.py
├── vectorizer.py
├── requirements.txt
├── .gitignore
└── data/
    └── signals.jsonl   ← gerado localmente, incluir no deploy inicial
```

---

## Passo 1 — Gerar os dados localmente

Antes de subir para o GitHub, rode a ingestão na sua máquina para ter signals:

```bash
python ingestion.py
```

Confirme que o arquivo foi criado:
```bash
wc -l data/signals.jsonl
```

---

## Passo 2 — Criar repositório no GitHub

1. Acesse github.com e faça login
2. Clique em **"New repository"**
3. Nome: `countercurrent`
4. Visibilidade: **Private** (recomendado)
5. Clique em **"Create repository"**

---

## Passo 3 — Subir os arquivos pelo terminal

No terminal do VS Code, dentro da pasta do projeto:

```bash
# Inicializar o git
git init

# Adicionar todos os arquivos (o .gitignore já protege .env e venv/)
git add .

# Verificar o que será enviado (confirme que .env NÃO aparece)
git status

# Criar o commit
git commit -m "Countercurrent.ai v2 - initial deploy"

# Conectar ao repositório do GitHub (substitua SEU_USUARIO pelo seu usuário)
git remote add origin https://github.com/SEU_USUARIO/countercurrent.git

# Enviar
git branch -M main
git push -u origin main
```

---

## Passo 4 — Deploy no Streamlit Cloud

1. Acesse **share.streamlit.io**
2. Clique em **"New app"**
3. Conecte sua conta GitHub se ainda não conectou
4. Selecione:
   - Repository: `countercurrent`
   - Branch: `main`
   - Main file path: `app.py`
5. Clique em **"Deploy"**

---

## Passo 5 — Configurar as chaves secretas no Streamlit Cloud

⚠️ Este passo é obrigatório — sem ele o app não funciona.

1. No painel do Streamlit Cloud, clique em **"Settings"** no seu app
2. Clique em **"Secrets"**
3. Cole exatamente assim (com suas chaves reais):

```toml
GOOGLE_API_KEY = "sua_chave_google"
APIFY_API_TOKEN = "sua_chave_apify"
PINECONE_API_KEY = "sua_chave_pinecone"
PINECONE_INDEX_NAME = "countercurrent-signals"
```

4. Clique em **"Save"**
5. O app vai reiniciar automaticamente

---

## Passo 6 — Compartilhar o link

Após o deploy, o Streamlit Cloud vai gerar um link tipo:
```
https://countercurrent.streamlit.app
```

Compartilhe com seus colegas. O app fica no ar 24/7 gratuitamente.

---

## Atualizar o app depois (quando mudar o código)

Sempre que fizer mudanças locais, rode:

```bash
git add .
git commit -m "descrição da mudança"
git push
```

O Streamlit Cloud detecta o push e atualiza o app automaticamente.

---

## Atualizar os dados (rodar ingestão nova)

Como o Streamlit Cloud não roda o `ingestion.py` automaticamente,
o fluxo por enquanto é:

1. Rodar `python ingestion.py` localmente
2. Fazer push do `data/signals.jsonl` atualizado
3. O app recarrega com os novos dados

```bash
git add data/signals.jsonl
git commit -m "update signals"
git push
```

---

## Problemas comuns

| Erro | Solução |
|---|---|
| "Module not found" | Verifique se o pacote está no requirements.txt |
| App abre mas sem dados | Verifique se data/signals.jsonl está no repositório |
| "API key not found" | Verifique os Secrets no Streamlit Cloud (Passo 5) |
| App lento para carregar | Normal na primeira vez — Streamlit Cloud faz "cold start" |
