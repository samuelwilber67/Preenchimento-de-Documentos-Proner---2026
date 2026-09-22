# Preenchedor de Documentos PRONER

App que preenche os 15 documentos originais do MAPA/PRONER por substituição
de marcadores `{{TOKEN}}` dentro do próprio `.docx` — a formatação original
(tabelas, cores, fontes, bordas) nunca é alterada, só o texto dos campos.

Diferente da versão em HTML (artifact do Claude), esta versão em
**Streamlit** roda como um site comum: qualquer pessoa que abrir o link
consegue baixar os documentos, **sem precisar de login na Claude**.

---

## 📁 O que tem neste pacote

```
proner-preenchedor/
├── streamlit_app.py      ← o app inteiro (interface + motor de preenchimento)
├── requirements.txt      ← bibliotecas Python necessárias
├── runtime.txt            ← versão do Python a usar no deploy
├── .gitignore
├── README.md              ← este arquivo
└── templates/             ← os 15 .docx ORIGINAIS já com os marcadores {{TOKEN}}
    ├── ART_FISCALIZACAO_OU_DECLARACAO_RESP_TECNICO.docx
    ├── DECLARACAO_CONFORM_LISTA_VER_ART.docx
    ├── ... (15 arquivos)
```

**Importante:** a pasta `templates/` precisa ir para o GitHub junto com o
código — é ela que contém os documentos que o app preenche. Não delete nem
renomeie esses arquivos.

---

## 🚀 Passo a passo para publicar (sem usar linha de comando)

### Parte 1 — Criar o repositório no GitHub

1. Crie uma conta em [github.com](https://github.com) (se ainda não tiver).
2. Clique no **+** no canto superior direito → **New repository**.
3. Dê um nome, por exemplo `proner-preenchedor`.
4. Deixe como **Public** (o plano gratuito do Streamlit Cloud permite só 1
   app privado — deixando público você não tem esse limite. Os documentos
   gerados não ficam públicos, só o código do app).
5. Clique em **Create repository**.

### Parte 2 — Subir os arquivos

1. Na página do repositório recém-criado, clique em **uploading an
   existing file** (ou **Add file → Upload files**).
2. Arraste **todos os arquivos e a pasta `templates/`** deste pacote para
   a área de upload (o GitHub aceita arrastar a pasta inteira, com os 15
   `.docx` dentro).
3. Espere o upload terminar (pode levar um minuto, são vários arquivos).
4. Role para baixo e clique em **Commit changes**.

> Se preferir usar o Git pela linha de comando (opcional, só para quem já
> tem familiaridade):
> ```bash
> git clone https://github.com/SEU_USUARIO/proner-preenchedor.git
> cd proner-preenchedor
> # copie os arquivos deste pacote para dentro desta pasta
> git add .
> git commit -m "Primeira versão do app"
> git push
> ```

### Parte 3 — Publicar no Streamlit Community Cloud (gratuito)

1. Acesse [share.streamlit.io](https://share.streamlit.io).
2. Clique em **Continue with GitHub** e autorize o acesso.
3. Clique em **Create app** (ou **New app**).
4. Escolha **"Deploy a public app from GitHub"** (ou selecione o
   repositório diretamente, se aparecer na lista).
5. Preencha:
   - **Repository:** `SEU_USUARIO/proner-preenchedor`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
6. Clique em **Deploy**.
7. Aguarde 1–3 minutos enquanto o Streamlit instala as dependências
   (`streamlit`, `Pillow`) e inicia o app.

Pronto — você recebe um link parecido com
`https://seu-usuario-proner-preenchedor.streamlit.app`, que pode ser
compartilhado com qualquer pessoa. Quem abrir o link **não precisa de
conta em nada** — o botão de download funciona direto, é um download
normal do navegador.

---

## 🔁 Como atualizar o app depois de publicado

Qualquer alteração que você enviar para o repositório no GitHub (novo
commit na branch `main`) é aplicada automaticamente no app publicado em
menos de um minuto — não precisa reconfigurar nada no Streamlit Cloud.

Para editar um arquivo direto pelo site do GitHub: abra o arquivo no
repositório, clique no ícone de lápis (✏️ Edit), altere, e clique em
**Commit changes**.

---

## ⚠️ Limites do plano gratuito do Streamlit Community Cloud

- O app "dorme" depois de ~12 horas sem visitas — a próxima pessoa que
  abrir o link espera uns 10–30 segundos enquanto ele "acorda". Isso é
  normal e não indica erro.
- Só é permitido **1 app privado** por conta gratuita — por isso a
  recomendação de deixar o repositório público (o código de preenchimento
  é o mesmo enviado à Claude, sem dados sensíveis; nenhum dado que o
  usuário digita no formulário é salvo em lugar nenhum).
- Limite de memória de ~1 GB, mais do que suficiente para este app.

Se no futuro precisar de um app sempre ativo, com domínio próprio ou sem
esses limites, existem alternativas pagas simples (ex: Railway, Render, ou
serviços que hospedam Streamlit diretamente) — mas para o uso descrito
aqui, o plano gratuito atende bem.

---

## 🛠️ Rodando localmente (opcional, para testar antes de publicar)

Se tiver Python instalado no seu computador:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

O navegador abre automaticamente em `http://localhost:8501`.

---

## 🧩 Como o preenchimento funciona (para referência futura)

Cada arquivo em `templates/` é o `.docx` original do MAPA, mas com os
campos variáveis (Convênio, Município, CNPJ etc.) já substituídos por
marcadores como `{{MUNICIPIO}}`, `{{CONVENIO}}`, `{{NOME_PREFEITO}}`.

Ao gerar um documento, o app:
1. Abre o `.docx` como um `.zip` (é isso que um `.docx` é internamente).
2. Substitui cada `{{TOKEN}}` pelo valor digitado no formulário, direto no
   XML interno — sem tocar em nenhuma tabela, cor, fonte ou espaçamento.
3. Aplica destaque amarelo automático só no texto que foi substituído
   (para facilitar a revisão), preservando a formatação original ao redor.
4. Se uma logo foi enviada, troca a imagem-placeholder do cabeçalho pela
   logo enviada, mantendo a proporção original (sem distorcer).
5. Devolve o `.docx` pronto para download.

Se precisar adicionar um novo campo no futuro: adicione uma entrada na
lista `FIELDS` em `streamlit_app.py`, e insira o marcador `{{NOVO_CAMPO}}`
correspondente dentro do `.docx` do template (no lugar certo do texto).
