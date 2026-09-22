"""
Preenchedor de Documentos PRONER — versão Streamlit
=====================================================
Preenche os 15 documentos ORIGINAIS do MAPA/PRONER por substituição pura
de marcadores {{TOKEN}} dentro do XML do .docx (a mesma técnica de
"bookmark" / mail-merge do Word) — nenhuma formatação, tabela, cor ou
fonte do original é alterada. Só o texto dos campos é trocado.

Como funciona, em resumo:
  1. Cada arquivo em templates/ é o .docx original do MAPA, mas com os
     campos variáveis (Convênio, Município, CNPJ, etc.) já substituídos
     por marcadores {{NOME_DO_CAMPO}}.
  2. Ao gerar, abrimos o .docx como um .zip (é isso que um .docx é),
     pegamos os arquivos XML internos (word/document.xml e outros),
     trocamos {{TOKEN}} pelo valor que o usuário digitou, e devolvemos
     como um novo .docx.
  3. Cada run de texto substituído recebe destaque amarelo automático,
     para facilitar a revisão.
  4. Se uma logo for enviada, ela substitui a imagem-placeholder do
     cabeçalho (mantendo a proporção original, sem distorcer).
"""

import io
import re
import zipfile
from pathlib import Path
from typing import Optional, Tuple

import streamlit as st
from PIL import Image

# ─────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────

TEMPLATES_DIR = Path(__file__).parent / "templates"

DOCS = [
    ("ART_FISCALIZACAO_OU_DECLARACAO_RESP_TECNICO", "ART / Declaração Resp. Técnico"),
    ("DECLARACAO_CONFORM_LISTA_VER_ART", "Declaração Conformidade Acessibilidade"),
    ("DECLARACAO_DESONERACAO_FOLHA", "Declaração Desoneração de Folha"),
    ("DECLARACAO_INFORMACOES_MUNICIPAIS", "Declaração Informações Municipais"),
    ("DECLARACAO_PRODUCAO_AGROPECUARIA", "Declaração Produção Agropecuária"),
    ("DEFINICAO_DO_OBJETO", "Definição do Objeto"),
    ("DIAGNOSTICO_PRELIMINAR_TRECHO", "Diagnóstico Preliminar do Trecho"),
    ("DOCUMENTO_DOMINIO_AREA", "Documento Domínio da Área"),
    ("ESTUDO_TECNICO_PRELIMINAR_ETP", "Estudo Técnico Preliminar (ETP)"),
    ("LICENCA_AMBIENTAL_ESTRADA", "Licença Ambiental – Estrada"),
    ("LICENCA_AMBIENTAL_JAZIDA", "Licença Ambiental – Jazida"),
    ("MAPA_CROQUI_PRELIMINAR", "Mapa/Croqui Preliminar"),
    ("MEMORIAL_DESCRITIVO", "Memorial Descritivo"),
    ("PLANO_DE_SUSTENTABILIDADE", "Plano de Sustentabilidade"),
    ("RELATORIO_FOTOGRAFICO_GEORREFERENCIADO", "Relatório Fotográfico Georreferenciado"),
]

# (field_id, label, placeholder, default_when_blank)
FIELDS = [
    ("CONVENIO", "Nº do Convênio / Ano", "ex: 123456/2025", "XXXXXX/XXXX"),
    ("MUNICIPIO", "Município", "Nome do município", "XXXXXXXXXX"),
    ("UF", "UF", "ex: MG", "XX"),
    ("OBJETO", "Objeto do Convênio", "Descrição do objeto conforme cadastrado no Transferegov.br",
     "Objeto cadastrado no Transferegov.br"),
    ("NOME_PREFEITO", "Nome do(a) Prefeito(a)", "Nome completo", "NOME DO PREFEITO(A)"),
    ("CNPJ_PREFEITURA", "CNPJ da Prefeitura", "00.000.000/0001-00", "XX.XXX.XXX/XXXX-XX"),
    ("ENDERECO_SEDE", "Endereço da Sede Administrativa", "Rua, nº, bairro — Município/UF", "ENDEREÇO DA SEDE"),
    ("DESCRICAO_OBRA", "Descrição da Obra", "ex: Recuperação de estrada vicinal com revestimento primário",
     "DESCRIÇÃO DA OBRA"),
    ("LOCALIZACAO_TRECHO", "Localização / Trecho", "ex: Estrada Municipal X, entre a localidade A e B",
     "LOCALIZAÇÃO DO TRECHO"),
    ("DATA_REFERENCIA", "Data e local de referência (assinaturas)", "ex: São João da Serra/MG, 22/09/2025", None),
    ("NOME_ENGENHEIRO", "Nome do Engenheiro", "Nome completo", "NOME DO ENGENHEIRO"),
    ("ESPECIALIDADE_ENG", "Especialidade", "ex: Engenheiro Civil", "ENGENHEIRO CIVIL"),
    ("CREA_ENGENHEIRO", "CREA / Estado nº", "ex: CREA/MG nº 123456D/MG", "CREA/XX nº XXXXD/XX"),
    ("FUNCAO_ENG", "Função", "ex: Responsável técnico pela Fiscalização", "Responsável técnico"),
    ("POPULACAO_TOTAL", "População Total do Município", "ex: 25.400", "XXXXX"),
    ("POPULACAO_AFETADA", "População Afetada pela Intervenção", "ex: 7.300", "XXXXX"),
    ("RENDA_PER_CAPITA", "Renda Per Capita", "ex: R$ 735,00", "R$ X.XXX,XX"),
    ("IMPACTO_LOGISTICO", "Impacto Logístico (% da malha rural)", "ex: 28,7%", "XX%"),
    ("EXTENSAO_TOTAL", "Extensão Total de Estradas Vicinais", "ex: 680 km", "XXX km"),
    ("PRECIPITACAO", "Precipitação Pluvial Média Anual", "ex: 1.200 mm/ano", "X.XXX mm/ano"),
    ("LICENCA_JAZIDA", "Licença Ambiental da Jazida — nº do protocolo / data",
     "ex: Protocolo nº 998877, de 10/05/2025", "[Nº DO PROTOCOLO]"),
    ("LEGENDA_MAPA", "Legenda do Mapa/Fotos — UF ou identificação da região", "ex: MG", "XX"),
]
FIELD_IDS = [f[0] for f in FIELDS]

MAX_LOGO_W_PX = 130
MAX_LOGO_H_PX = 100
EMU_PER_PX = 9525  # at 96 DPI

# ─────────────────────────────────────────────────────────────────────────
# CORE ENGINE — identical logic to the browser/JSZip version, in Python
# ─────────────────────────────────────────────────────────────────────────

def xml_escape(value: str) -> str:
    return (str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


_RUN_WITH_TOKEN_RE = re.compile(
    r'<w:r\b[^>]*>(?:(?!<w:r\b)(?!</w:r>)[\s\S])*?\{\{[A-Z0-9_]+\}\}(?:(?!<w:r\b)(?!</w:r>)[\s\S])*?</w:r>'
)
_T_TAG_RE = re.compile(r'<w:t([^>]*)>([\s\S]*?)</w:t>')
_RPR_RE = re.compile(r'<w:rPr>([\s\S]*?)</w:rPr>')
_TOKEN_SPLIT_RE = re.compile(r'(\{\{[A-Z0-9_]+\}\})')
_TOKEN_FULL_RE = re.compile(r'^\{\{[A-Z0-9_]+\}\}$')
_HIGHLIGHT_RE = re.compile(r'<w:highlight\b[^/]*/>')


def inject_highlight_runs(xml_text: str) -> str:
    """Splits any run containing {{TOKEN}} markers into separate runs so that
    ONLY the token (the substituted value) gets a yellow highlight added to
    its formatting — the literal text around it keeps the original run
    formatting completely untouched."""

    def _replace_run(m: "re.Match") -> str:
        run_xml = m.group(0)
        t_match = _T_TAG_RE.search(run_xml)
        if not t_match:
            # Runs without a <w:t> (e.g. the logo's <w:drawing>) are left alone.
            return run_xml

        text = t_match.group(2)
        rpr_match = _RPR_RE.search(run_xml)
        base_rpr = rpr_match.group(1) if rpr_match else ""

        parts = [p for p in _TOKEN_SPLIT_RE.split(text) if p]
        if not parts:
            return run_xml

        rebuilt = []
        for part in parts:
            is_token = bool(_TOKEN_FULL_RE.match(part))
            rpr = base_rpr
            if is_token:
                if _HIGHLIGHT_RE.search(rpr):
                    rpr = _HIGHLIGHT_RE.sub('<w:highlight w:val="yellow"/>', rpr, count=1)
                else:
                    rpr = rpr + '<w:highlight w:val="yellow"/>'
            rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
            rebuilt.append(f'<w:r>{rpr_xml}<w:t xml:space="preserve">{part}</w:t></w:r>')
        return "".join(rebuilt)

    return _RUN_WITH_TOKEN_RE.sub(_replace_run, xml_text)


_LOGO_MEDIA_RE = re.compile(r'word/media/logo_header\d+\.png$')


def compute_logo_extent_emu(width_px: int, height_px: int) -> Tuple[int, int]:
    """Fits the logo inside a standard bounding box, preserving its
    original aspect ratio (never distorted), and returns (cx, cy) in EMU."""
    if not width_px or not height_px:
        return 900000, 900000
    ratio = min(MAX_LOGO_W_PX / width_px, MAX_LOGO_H_PX / height_px, 1)
    w = round(width_px * ratio) or MAX_LOGO_W_PX
    h = round(height_px * ratio) or MAX_LOGO_H_PX
    return w * EMU_PER_PX, h * EMU_PER_PX


def fill_template(doc_id: str, field_values: dict, logo_png_bytes: Optional[bytes],
                   logo_cx: int, logo_cy: int) -> bytes:
    """Loads the ORIGINAL .docx template (unchanged bytes) and does pure
    text substitution of {{TOKEN}} markers inside its XML parts — this
    never rebuilds the document; every other byte (styles, tables, borders,
    colors, fonts, spacing) stays exactly as in the original file."""

    template_path = TEMPLATES_DIR / f"{doc_id}.docx"
    with open(template_path, "rb") as f:
        original_bytes = f.read()

    replacements = {key: xml_escape(field_values.get(key, "")) for key in FIELD_IDS}
    replacements["LOGO_CX"] = str(logo_cx)
    replacements["LOGO_CY"] = str(logo_cy)

    src_zip = zipfile.ZipFile(io.BytesIO(original_bytes), "r")
    out_buffer = io.BytesIO()
    out_zip = zipfile.ZipFile(out_buffer, "w", zipfile.ZIP_DEFLATED)

    for item in src_zip.infolist():
        data = src_zip.read(item.filename)
        is_xml_part = item.filename.endswith(".xml") or item.filename.endswith(".rels")
        is_logo_media = bool(_LOGO_MEDIA_RE.match(item.filename))

        if is_xml_part:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                out_zip.writestr(item, data)
                continue
            if "{{" in text:
                text = inject_highlight_runs(text)
                for key, value in replacements.items():
                    token = "{{" + key + "}}"
                    if token in text:
                        text = text.replace(token, value)
                data = text.encode("utf-8")
            out_zip.writestr(item, data)
        elif is_logo_media and logo_png_bytes:
            out_zip.writestr(item, logo_png_bytes)
        else:
            out_zip.writestr(item, data)

    out_zip.close()
    src_zip.close()
    return out_buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Preenchedor de Documentos PRONER", page_icon="📋", layout="centered")

st.title("📋 Preenchedor de Documentos PRONER")
st.caption("Preencha uma vez — os documentos originais são preenchidos, sem alterar a formatação.")

# ── Logo ──────────────────────────────────────────────────────────────
st.subheader("🏛️ Logotipo da Prefeitura")
st.caption("Será inserido no cabeçalho de cada documento, centralizado, em tamanho padrão "
           "(proporção original preservada).")
logo_file = st.file_uploader("Selecionar imagem", type=["png", "jpg", "jpeg", "webp", "bmp"])

logo_png_bytes = None
logo_cx, logo_cy = 900000, 900000  # default square box, matches the placeholder graphic
if logo_file is not None:
    img = Image.open(logo_file).convert("RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    logo_png_bytes = buf.getvalue()
    logo_cx, logo_cy = compute_logo_extent_emu(img.width, img.height)
    st.image(logo_png_bytes, width=140, caption="Pré-visualização")

st.divider()

# ── Form ──────────────────────────────────────────────────────────────
st.subheader("📋 Dados do Convênio")
c1, c2, c3 = st.columns(3)
field_values = {}
field_values["CONVENIO"] = c1.text_input("Nº do Convênio / Ano", placeholder="ex: 123456/2025")
field_values["MUNICIPIO"] = c2.text_input("Município", placeholder="Nome do município")
field_values["UF"] = c3.text_input("UF", placeholder="ex: MG", max_chars=2)
field_values["OBJETO"] = st.text_input(
    "Objeto do Convênio",
    placeholder="Descrição do objeto conforme cadastrado no Transferegov.br",
)

st.subheader("🏢 Dados da Prefeitura")
c1, c2 = st.columns(2)
field_values["NOME_PREFEITO"] = c1.text_input("Nome do(a) Prefeito(a)", placeholder="Nome completo")
field_values["CNPJ_PREFEITURA"] = c2.text_input("CNPJ da Prefeitura", placeholder="00.000.000/0001-00")
field_values["ENDERECO_SEDE"] = st.text_input(
    "Endereço da Sede Administrativa", placeholder="Rua, nº, bairro — Município/UF"
)

st.subheader("🛣️ Dados da Obra / Trecho")
field_values["DESCRICAO_OBRA"] = st.text_input(
    "Descrição da Obra", placeholder="ex: Recuperação de estrada vicinal com revestimento primário"
)
field_values["LOCALIZACAO_TRECHO"] = st.text_input(
    "Localização / Trecho", placeholder="ex: Estrada Municipal X, entre a localidade A e B"
)
field_values["DATA_REFERENCIA"] = st.text_input(
    "Data e local de referência (assinaturas)", placeholder="ex: São João da Serra/MG, 22/09/2025"
)

st.subheader("👷 Responsável Técnico")
c1, c2 = st.columns(2)
field_values["NOME_ENGENHEIRO"] = c1.text_input("Nome do Engenheiro", placeholder="Nome completo")
field_values["ESPECIALIDADE_ENG"] = c2.text_input("Especialidade", placeholder="ex: Engenheiro Civil")
c1, c2 = st.columns(2)
field_values["CREA_ENGENHEIRO"] = c1.text_input("CREA / Estado nº", placeholder="ex: CREA/MG nº 123456D/MG")
field_values["FUNCAO_ENG"] = c2.text_input("Função", placeholder="ex: Responsável técnico pela Fiscalização")

st.subheader("📊 Indicadores Municipais")
c1, c2, c3 = st.columns(3)
field_values["POPULACAO_TOTAL"] = c1.text_input("População Total", placeholder="ex: 25.400")
field_values["POPULACAO_AFETADA"] = c2.text_input("População Afetada", placeholder="ex: 7.300")
field_values["RENDA_PER_CAPITA"] = c3.text_input("Renda Per Capita", placeholder="ex: R$ 735,00")
c1, c2, c3 = st.columns(3)
field_values["IMPACTO_LOGISTICO"] = c1.text_input("Impacto Logístico", placeholder="ex: 28,7%")
field_values["EXTENSAO_TOTAL"] = c2.text_input("Extensão Total de Estradas", placeholder="ex: 680 km")
field_values["PRECIPITACAO"] = c3.text_input("Precipitação Média Anual", placeholder="ex: 1.200 mm/ano")

st.subheader("🔴 Campos Específicos")
st.caption("Estes campos aparecem em vermelho nos documentos originais (chamando atenção para preenchimento).")
field_values["LICENCA_JAZIDA"] = st.text_input(
    "Licença Ambiental da Jazida — nº do protocolo / data", placeholder="ex: Protocolo nº 998877, de 10/05/2025"
)
field_values["LEGENDA_MAPA"] = st.text_input(
    "Legenda do Mapa/Fotos — UF ou identificação da região", placeholder="ex: MG"
)

# Fill in defaults for anything left blank (mirrors the JS getFieldValues() logic)
_defaults_lookup = {f[0]: f[3] for f in FIELDS}
municipio_val = field_values.get("MUNICIPIO") or "XXXXXXXXXX"
uf_val = field_values.get("UF") or "XX"
_defaults_lookup["DATA_REFERENCIA"] = f"{municipio_val}/{uf_val}, XX/XX/XXXX"
for fid in FIELD_IDS:
    if not field_values.get(fid):
        field_values[fid] = _defaults_lookup.get(fid) or ""

st.divider()

# ── Document selection ────────────────────────────────────────────────
st.subheader("📁 Selecionar Documentos a Gerar")
select_all = st.checkbox("Selecionar todos", value=True)
selected_docs = []
cols = st.columns(2)
for i, (doc_id, label) in enumerate(DOCS):
    col = cols[i % 2]
    checked = col.checkbox(label, value=select_all, key=f"doc_{doc_id}")
    if checked:
        selected_docs.append(doc_id)

st.divider()

# ── Generate ──────────────────────────────────────────────────────────
if st.button("⚡ Gerar Documentos", type="primary", use_container_width=True):
    if not selected_docs:
        st.warning("Selecione pelo menos um documento.")
    else:
        generated = []
        progress = st.progress(0, text="Preenchendo documentos...")
        for i, doc_id in enumerate(selected_docs):
            label = dict(DOCS)[doc_id]
            progress.progress((i + 1) / len(selected_docs), text=f"Preenchendo: {label}...")
            try:
                doc_bytes = fill_template(doc_id, field_values, logo_png_bytes, logo_cx, logo_cy)
                generated.append((doc_id, label, doc_bytes))
            except Exception as e:
                st.error(f"Erro ao preencher {label}: {e}")
        progress.empty()

        if generated:
            st.success(f"{len(generated)} documento(s) gerado(s) com sucesso!")

            for doc_id, label, doc_bytes in generated:
                st.download_button(
                    label=f"⬇ Baixar {label}",
                    data=doc_bytes,
                    file_name=f"{doc_id}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key=f"dl_{doc_id}",
                    use_container_width=True,
                )

            if len(generated) > 1:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for doc_id, _label, doc_bytes in generated:
                        zf.writestr(f"{doc_id}.docx", doc_bytes)
                municipio_safe = (field_values.get("MUNICIPIO") or "municipio").replace(" ", "_")
                convenio_safe = (field_values.get("CONVENIO") or "convenio").replace("/", "-")
                st.download_button(
                    label="📦 Baixar todos em ZIP",
                    data=zip_buffer.getvalue(),
                    file_name=f"DOCUMENTOS_{municipio_safe}_{convenio_safe}.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

st.divider()
st.caption(
    "Os documentos gerados são os arquivos originais do MAPA/PRONER, com a formatação preservada — "
    "apenas os campos de dados são substituídos. Os valores preenchidos aparecem destacados em amarelo "
    "para facilitar a revisão."
)
