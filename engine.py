"""
Motor de preenchimento dos documentos PRONER.

Princípio central: os arquivos em templates/ são os .docx ORIGINAIS do MAPA,
com os campos variáveis trocados por marcadores {{TOKEN}}. O preenchimento é
substituição de texto dentro do XML do .docx — nenhuma formatação, tabela,
cor ou fonte do original é reconstruída ou alterada.
"""

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
BASE_DNIT_PATH = BASE_DIR / "base" / "base_dnit.json"

# ─────────────────────────────────────────────────────────────────────────
# Catálogo de documentos
# ─────────────────────────────────────────────────────────────────────────

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

# Campos simples do formulário: (id, rótulo, placeholder, valor padrão se vazio)
FIELDS = [
    ("CONVENIO", "Nº do Convênio/Proposta", "ex: 034959/2026", "XXXXXX/XXXX"),
    ("MUNICIPIO", "Município", "Nome do município", "XXXXXXXXXX"),
    ("UF", "UF", "ex: MA", "XX"),
    ("OBJETO", "Objeto (cadastrado no TransfereGov)", "", "Objeto cadastrado no TransfereGov"),
    ("DESCRICAO_OBJETO", "Descrição do Objeto", "", ""),
    ("EIXO", "Eixo do objeto (IN 25)", "", ""),
    ("NOME_PREFEITO", "Nome do(a) Prefeito(a)", "Nome completo", "NOME DO PREFEITO(A)"),
    ("CNPJ_PREFEITURA", "CNPJ da Prefeitura", "00.000.000/0001-00", "XX.XXX.XXX/XXXX-XX"),
    ("ENDERECO_SEDE", "Endereço da Sede Administrativa", "", "ENDEREÇO DA SEDE"),
    ("DESCRICAO_OBRA", "Descrição da Obra", "", "DESCRIÇÃO DA OBRA"),
    ("LOCALIZACAO_TRECHO", "Localização / Trecho", "", "LOCALIZAÇÃO DO TRECHO"),
    ("DATA_REFERENCIA", "Data e local de referência", "ex: João Lisboa/MA, 23/09/2026", None),
    ("NOME_ENGENHEIRO", "Nome do Engenheiro", "", "NOME DO ENGENHEIRO"),
    ("ESPECIALIDADE_ENG", "Especialidade", "ex: Engenheiro Civil", "ENGENHEIRO CIVIL"),
    ("CREA_ENGENHEIRO", "CREA nº", "ex: CREA/MA nº 12345D/MA", "CREA/XX nº XXXXD/XX"),
    ("FUNCAO_ENG", "Função", "", "Responsável técnico"),
    ("POPULACAO_TOTAL", "População Total", "", "XXXXX"),
    ("POPULACAO_AFETADA", "População Afetada", "", "XXXXX"),
    ("RENDA_PER_CAPITA", "Renda Per Capita", "", "R$ X.XXX,XX"),
    ("IMPACTO_LOGISTICO", "Impacto Logístico", "", "XX%"),
    ("EXTENSAO_TOTAL", "Extensão Total de Estradas", "", "XXX km"),
    ("PRECIPITACAO", "Precipitação Média Anual", "", "X.XXX mm/ano"),
    ("LICENCA_JAZIDA", "Licença Ambiental da Jazida", "", "[Nº DO PROTOCOLO]"),
    ("LEGENDA_MAPA", "Legenda do Mapa/Fotos", "ex: MA", "XX"),
]
FIELD_IDS = [f[0] for f in FIELDS]

# Tokens derivados da escolha Convênio/Proposta e da desoneração
DERIVED_TOKEN_IDS = [
    "INSTRUMENTO", "INSTRUMENTO_MIN", "DO_INSTRUMENTO", "DO_INSTRUMENTO_MIN",
    "DO_INSTRUMENTO_MAI", "DO_INSTRUMENTO_TIT", "NUM_CONVENIO", "NUM_PROPOSTA",
    "OPCAO_DESONERACAO", "MEMORIAL_SERVICOS",
]

MAX_LOGO_W_PX = 130
MAX_LOGO_H_PX = 100
EMU_PER_PX = 9525  # a 96 DPI


def derive_instrumento_tokens(tipo: str, numero: str) -> Dict[str, str]:
    """tipo: 'Convênio' ou 'Proposta'. Gera as variações de caixa e gênero usadas
    nos documentos, e preenche só a linha correspondente no quadro que traz
    'Convênio:' e 'Proposta:' lado a lado."""
    if tipo == "Proposta":
        return {
            "INSTRUMENTO": "Proposta",
            "INSTRUMENTO_MIN": "proposta",
            "DO_INSTRUMENTO": "da Proposta",
            "DO_INSTRUMENTO_MIN": "da proposta",
            "DO_INSTRUMENTO_MAI": "DA PROPOSTA",
            "DO_INSTRUMENTO_TIT": "Da Proposta",
            "NUM_CONVENIO": "—",
            "NUM_PROPOSTA": numero,
        }
    return {
        "INSTRUMENTO": "Convênio",
        "INSTRUMENTO_MIN": "convênio",
        "DO_INSTRUMENTO": "do Convênio",
        "DO_INSTRUMENTO_MIN": "do convênio",
        "DO_INSTRUMENTO_MAI": "DO CONVÊNIO",
        "DO_INSTRUMENTO_TIT": "Do Convênio",
        "NUM_CONVENIO": numero,
        "NUM_PROPOSTA": "—",
    }


# ─────────────────────────────────────────────────────────────────────────
# Substituição de tokens + destaque amarelo
# ─────────────────────────────────────────────────────────────────────────

def xml_escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


_RUN_WITH_TOKEN_RE = re.compile(
    r'<w:r\b[^>]*>(?:(?!<w:r\b)(?!</w:r>)[\s\S])*?\{\{[A-Z0-9_]+\}\}'
    r'(?:(?!<w:r\b)(?!</w:r>)[\s\S])*?</w:r>'
)
_T_TAG_RE = re.compile(r'<w:t([^>]*)>([\s\S]*?)</w:t>')
_RPR_RE = re.compile(r'<w:rPr>([\s\S]*?)</w:rPr>')
_TOKEN_SPLIT_RE = re.compile(r'(\{\{[A-Z0-9_]+\}\})')
_TOKEN_FULL_RE = re.compile(r'^\{\{[A-Z0-9_]+\}\}$')
_HIGHLIGHT_RE = re.compile(r'<w:highlight\b[^/]*/>')
_LOGO_MEDIA_RE = re.compile(r'word/media/logo_header\d+\.png$')


def inject_highlight_runs(xml_text: str) -> str:
    """Separa cada {{TOKEN}} em um run próprio, com destaque amarelo, mantendo
    o texto literal ao redor exatamente com a formatação original."""

    def _replace_run(m) -> str:
        run_xml = m.group(0)
        t_match = _T_TAG_RE.search(run_xml)
        if not t_match:
            return run_xml  # runs sem <w:t> (ex.: a logo) ficam intactos

        text = t_match.group(2)
        rpr_match = _RPR_RE.search(run_xml)
        base_rpr = rpr_match.group(1) if rpr_match else ""

        parts = [p for p in _TOKEN_SPLIT_RE.split(text) if p]
        if not parts:
            return run_xml

        rebuilt = []
        for part in parts:
            rpr = base_rpr
            if _TOKEN_FULL_RE.match(part):
                if _HIGHLIGHT_RE.search(rpr):
                    rpr = _HIGHLIGHT_RE.sub('<w:highlight w:val="yellow"/>', rpr, count=1)
                else:
                    rpr = rpr + '<w:highlight w:val="yellow"/>'
            rpr_xml = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
            rebuilt.append(
                f'<w:r>{rpr_xml}<w:t xml:space="preserve">{part}</w:t></w:r>')
        return "".join(rebuilt)

    return _RUN_WITH_TOKEN_RE.sub(_replace_run, xml_text)


# ─────────────────────────────────────────────────────────────────────────
# Expansão da tabela de trechos (Definição do Objeto)
# ─────────────────────────────────────────────────────────────────────────

def expand_trecho_rows(xml: str, trechos: List[dict]) -> str:
    """A linha-modelo da tabela contém {{TRECHO_NOME}}. Ela é clonada uma vez
    por trecho informado, preservando integralmente a formatação da tabela."""
    i = xml.find("{{TRECHO_NOME}}")
    if i == -1:
        return xml
    # Atenção: buscar "<w:tr" cru casaria com "<w:trPr" (que vem logo depois da
    # abertura da linha); é preciso exigir ">" ou espaço após "tr".
    starts = [m.start() for m in re.finditer(r'<w:tr[ >]', xml[:i])]
    if not starts:
        return xml
    start = starts[-1]
    end = xml.find("</w:tr>", i) + len("</w:tr>")
    if end <= start:
        return xml
    row_template = xml[start:end]

    if not trechos:
        trechos = [{"nome": "", "coord_ini": "", "coord_fim": "", "extensao": ""}]

    # Os valores não são inseridos aqui: cada linha recebe tokens indexados
    # ({{TRECHO_NOME_0}}, ...) para que a etapa de destaque amarelo trate os
    # trechos exatamente como qualquer outro campo substituído.
    rows = []
    for idx in range(len(trechos)):
        row = row_template
        for base_token in ("TRECHO_NOME", "TRECHO_COORD", "TRECHO_EXT"):
            row = row.replace("{{" + base_token + "}}", "{{" + base_token + f"_{idx}}}}}")
        rows.append(row)

    return xml[:start] + "".join(rows) + xml[end:]


# ─────────────────────────────────────────────────────────────────────────
# Quebras de linha dentro de um <w:t>
# ─────────────────────────────────────────────────────────────────────────

def _apply_linebreaks(xml: str) -> str:
    """Converte "\n" que tenham entrado no texto em quebras de linha do Word."""
    def fix(m):
        inner = m.group(2)
        if "\n" not in inner:
            return m.group(0)
        parts = inner.split("\n")
        joined = '</w:t><w:br/><w:t xml:space="preserve">'.join(parts)
        return f'<w:t{m.group(1)}>{joined}</w:t>'
    return _T_TAG_RE.sub(fix, xml)


# ─────────────────────────────────────────────────────────────────────────
# Logo
# ─────────────────────────────────────────────────────────────────────────

def compute_logo_extent_emu(width_px: int, height_px: int) -> Tuple[int, int]:
    """Encaixa a logo numa caixa padrão preservando a proporção original."""
    if not width_px or not height_px:
        return 900000, 900000
    ratio = min(MAX_LOGO_W_PX / width_px, MAX_LOGO_H_PX / height_px, 1)
    w = round(width_px * ratio) or MAX_LOGO_W_PX
    h = round(height_px * ratio) or MAX_LOGO_H_PX
    return w * EMU_PER_PX, h * EMU_PER_PX


# ─────────────────────────────────────────────────────────────────────────
# Preenchimento de um documento
# ─────────────────────────────────────────────────────────────────────────

def fill_template(doc_id: str, values: Dict[str, str],
                  logo_png_bytes: Optional[bytes] = None,
                  logo_cx: int = 900000, logo_cy: int = 900000,
                  trechos: Optional[List[dict]] = None) -> bytes:
    template_path = TEMPLATES_DIR / f"{doc_id}.docx"
    with open(template_path, "rb") as f:
        original_bytes = f.read()

    replacements = {k: xml_escape(v) for k, v in values.items()}
    for idx, t in enumerate(trechos or []):
        ini = (t.get("coord_ini") or "").strip()
        fim = (t.get("coord_fim") or "").strip()
        coord = f"Início: {ini or '—'}\nFim: {fim or '—'}" if (ini or fim) else ""
        replacements[f"TRECHO_NOME_{idx}"] = xml_escape(t.get("nome", ""))
        replacements[f"TRECHO_COORD_{idx}"] = xml_escape(coord)
        replacements[f"TRECHO_EXT_{idx}"] = xml_escape(t.get("extensao", ""))
    replacements["LOGO_CX"] = str(logo_cx)
    replacements["LOGO_CY"] = str(logo_cy)

    src_zip = zipfile.ZipFile(io.BytesIO(original_bytes), "r")
    out_buffer = io.BytesIO()
    out_zip = zipfile.ZipFile(out_buffer, "w", zipfile.ZIP_DEFLATED)

    for item in src_zip.infolist():
        data = src_zip.read(item.filename)
        is_xml = item.filename.endswith(".xml") or item.filename.endswith(".rels")
        is_logo = bool(_LOGO_MEDIA_RE.match(item.filename))

        if is_xml:
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                out_zip.writestr(item, data)
                continue
            if "{{" in text:
                if "{{TRECHO_NOME}}" in text:
                    text = expand_trecho_rows(text, trechos or [])
                text = inject_highlight_runs(text)
                for key, value in replacements.items():
                    token = "{{" + key + "}}"
                    if token in text:
                        text = text.replace(token, value)
                text = _apply_linebreaks(text)
                data = text.encode("utf-8")
            out_zip.writestr(item, data)
        elif is_logo and logo_png_bytes:
            out_zip.writestr(item, logo_png_bytes)
        else:
            out_zip.writestr(item, data)

    out_zip.close()
    src_zip.close()
    return out_buffer.getvalue()


# ─────────────────────────────────────────────────────────────────────────
# Item 6 — Memorial a partir da planilha orçamentária
# ─────────────────────────────────────────────────────────────────────────

def load_base_dnit() -> dict:
    if not BASE_DNIT_PATH.exists():
        return {"servicos": {}}
    with open(BASE_DNIT_PATH, encoding="utf-8") as f:
        return json.load(f)


_CODIGO_RE = re.compile(r'^\d{4,8}$')
_ITEM_RE = re.compile(r'^\d+(\.\d+)*$')


def parse_orcamento(rows: List[List[str]]) -> List[dict]:
    """Varre as linhas da planilha e devolve os serviços encontrados.

    Não assume posição fixa de colunas: em cada linha procura uma célula que
    pareça um item ("1.1", "2.3.1"), uma que pareça um código de composição
    (4 a 8 dígitos) e usa a célula de texto mais longa como descrição.
    """
    servicos = []
    for row in rows:
        cells = [("" if c is None else str(c)).strip() for c in row]
        if not any(cells):
            continue

        item = next((c for c in cells if _ITEM_RE.match(c)), "")
        codigo = next((c for c in cells
                       if _CODIGO_RE.match(c.replace(".", "").replace("-", ""))), "")
        if not codigo:
            continue

        textos = [c for c in cells if len(c) > 15 and not c.replace(",", "").replace(".", "").isdigit()]
        descricao = max(textos, key=len) if textos else ""
        if not descricao:
            continue

        servicos.append({"item": item, "codigo": codigo.replace(".", "").replace("-", ""),
                         "descricao": descricao})
    return servicos


def build_memorial(servicos: List[dict], base: dict) -> Tuple[str, List[dict]]:
    """Monta o texto do memorial na ordem da planilha.

    Devolve (texto, pendentes), onde 'pendentes' são os serviços cujo código
    não existe na base — eles entram no texto com a descrição da própria
    planilha e ficam sinalizados para preenchimento manual.
    """
    catalogo = base.get("servicos", {})
    blocos, pendentes = [], []

    for s in servicos:
        entrada = catalogo.get(s["codigo"])
        numero = s["item"] or ""
        prefixo = f"{numero} - " if numero else ""
        if entrada:
            titulo = entrada.get("titulo") or s["descricao"]
            corpo = entrada.get("descricao", "")
            blocos.append(f"{prefixo}{titulo}\n{corpo}")
        else:
            pendentes.append(s)
            blocos.append(
                f"{prefixo}{s['descricao']}\n"
                f"[DESCRIÇÃO TÉCNICA NÃO CADASTRADA NA BASE — código {s['codigo']}. "
                f"Preencher manualmente ou adicionar o serviço em base/base_dnit.json.]")

    return "\n\n".join(blocos), pendentes


# ─────────────────────────────────────────────────────────────────────────
# Indexação dos cadernos técnicos em PDF (base/cadernos/)
# ─────────────────────────────────────────────────────────────────────────

CADERNOS_DIR = BASE_DIR / "base" / "cadernos"
INDICE_PATH = BASE_DIR / "base" / "indice_cadernos.json"

# Títulos de seção do tipo "2.3.1 Revestimento primário" (nível 2 ou 3).
_SECAO_RE = re.compile(r'^\s*(\d+(?:\.\d+){1,2})\s+([^\d\n][^\n]{3,90})\s*$')
# Códigos de composição: 6 a 8 dígitos isolados.
_CODIGO_PDF_RE = re.compile(r'(?<!\d)(\d{6,8})(?!\d)')


def _extrair_texto_pdf(caminho) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(caminho))
    partes = []
    for pagina in reader.pages:
        try:
            partes.append(pagina.extract_text() or "")
        except Exception:
            partes.append("")
    return "\n".join(partes)


_CABECALHO_PAG_RE = re.compile(r'^\s*Caderno técnico do SICRO\b[^\n]*$', re.IGNORECASE)
_NUM_PAG_RE = re.compile(r'^\s*\d{1,4}\s*$')


def _limpar_corpo(texto: str) -> str:
    """Remove cabeçalho e número de página que a extração intercala no meio do
    texto, e compacta as linhas em branco excedentes."""
    linhas = []
    for linha in texto.splitlines():
        if _CABECALHO_PAG_RE.match(linha) or _NUM_PAG_RE.match(linha):
            continue
        linhas.append(linha.rstrip())
    limpo, vazias = [], 0
    for linha in linhas:
        if linha.strip():
            vazias = 0
            limpo.append(linha)
        else:
            vazias += 1
            if vazias <= 1:
                limpo.append("")
    return "\n".join(limpo).strip()


def _quebrar_em_secoes(texto: str) -> List[dict]:
    """Divide o texto em seções a partir dos títulos numerados. Uma seção vai do
    seu título até o título seguinte de nível igual ou superior.

    Quando o título do serviço quebra em duas linhas no PDF (ex.: 'Base e
    sub-base ... com mistura' / 'em usina'), a continuação é devolvida ao título
    em vez de ficar solta no início do corpo.
    """
    linhas = texto.splitlines()
    marcas = []
    for i, linha in enumerate(linhas):
        m = _SECAO_RE.match(linha)
        if m:
            numero, titulo = m.group(1), m.group(2).strip()
            marcas.append({"linha": i, "numero": numero,
                           "nivel": numero.count(".") + 1, "titulo": titulo})

    secoes = []
    for idx, marca in enumerate(marcas):
        fim = len(linhas)
        for seguinte in marcas[idx + 1:]:
            if seguinte["nivel"] <= marca["nivel"]:
                fim = seguinte["linha"]
                break

        corpo_linhas = linhas[marca["linha"] + 1:fim]
        titulo = marca["titulo"]

        # primeira linha não vazia começando em minúscula = resto do título
        for j, linha in enumerate(corpo_linhas):
            if not linha.strip():
                continue
            fragmento = linha.strip()
            if (fragmento[:1].islower() and len(fragmento) < 70
                    and not fragmento.startswith(("▪", "•", "-"))):
                titulo = f"{titulo} {fragmento}"
                corpo_linhas = corpo_linhas[j + 1:]
            break

        secoes.append({**marca, "titulo": titulo,
                       "texto": _limpar_corpo("\n".join(corpo_linhas))})
    return secoes


APENDICE_RE = re.compile(r'APÊNDICE\s+A\b[^\n]*RELAÇÃO DAS COMPOSIÇÕES', re.IGNORECASE)
_TOC_RE = re.compile(r'\.{4,}\s*\d+\s*$')          # linha do sumário ("... 22")
_SO_CODIGOS_RE = re.compile(r'[\d\s,e]*\d{6,8}[\d\s,e]*$')
_RODAPE_RE = re.compile(r'^(Caderno técnico|DNIT|\d+)\s*$')


def _mapa_codigos_apendice(texto: str) -> Dict[str, List[str]]:
    """O Apêndice A traz a tabela 'Relação das composições de custos por
    subgrupo', ligando cada subgrupo (ex.: '2.3.1 Revestimento primário') aos
    códigos SICRO. É a via confiável para associar código → seção: no corpo do
    caderno o código normalmente não aparece junto do texto do serviço.

    O layout varia conforme o extrator: o código pode sair na mesma linha do
    subgrupo ou em linhas seguintes (quando o título quebra ou há vários
    códigos). Por isso, tudo que vem depois de um cabeçalho de subgrupo e antes
    do próximo é varrido em busca de códigos.
    """
    achado = None
    for m in APENDICE_RE.finditer(texto):
        achado = m  # a primeira ocorrência costuma ser a do sumário
    if not achado:
        return {}

    mapa: Dict[str, List[str]] = {}
    secao_atual = None
    for linha in texto[achado.end():].splitlines():
        s = linha.strip()
        if not s or _RODAPE_RE.match(s) or _TOC_RE.search(s):
            continue
        if re.match(r'AP[ÊE]NDICE\s+[B-Z]\b', s, re.IGNORECASE):
            break  # fim da tabela do Apêndice A

        m = re.match(r'^(\d+(?:\.\d+){1,3})\s+(.*)$', s)
        if m and not re.fullmatch(r'[\d\s,e]+', s):
            secao_atual = m.group(1)
            mapa.setdefault(secao_atual, [])
            mapa[secao_atual].extend(re.findall(r'(?<!\d)\d{6,8}(?!\d)', m.group(2)))
            continue

        if secao_atual:
            mapa[secao_atual].extend(re.findall(r'(?<!\d)\d{6,8}(?!\d)', s))

    return {k: sorted(set(v)) for k, v in mapa.items() if v}


def indexar_cadernos(forcar: bool = False) -> dict:
    """Lê os PDFs de base/cadernos/ e monta o índice código → descrição.

    Estratégia: o Apêndice A liga subgrupo → códigos; o corpo do caderno traz o
    texto de cada subgrupo. Cruzando os dois, cada código recebe o texto da sua
    seção. Se o caderno não tiver Apêndice A, cai para a heurística de procurar
    o código dentro da própria seção.
    """
    if not CADERNOS_DIR.exists():
        return {"servicos": {}, "arquivos": [], "avisos": ["Pasta base/cadernos/ não existe."]}

    pdfs = sorted(p for p in CADERNOS_DIR.iterdir() if p.suffix.lower() == ".pdf")
    assinatura = {p.name: p.stat().st_size for p in pdfs}

    cache = None
    if INDICE_PATH.exists():
        try:
            with open(INDICE_PATH, encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = None

    if cache and not forcar and cache.get("assinatura") == assinatura:
        return cache

    # Índice presente mas sem PDFs na pasta: é o modo "só índice versionado"
    # (os PDFs ficam fora do repositório). Reindexar aqui apagaria a base.
    if cache and cache.get("servicos") and not pdfs:
        cache.setdefault("avisos", []).append(
            "Usando o índice já gerado — não há PDFs em base/cadernos/. "
            "Para reindexar, envie os PDFs para essa pasta.")
        return cache

    servicos: Dict[str, dict] = {}
    avisos: List[str] = []

    for pdf in pdfs:
        try:
            texto = _extrair_texto_pdf(pdf)
        except Exception as e:
            avisos.append(f"{pdf.name}: não consegui ler ({e}).")
            continue
        if not texto.strip():
            avisos.append(f"{pdf.name}: nenhum texto extraído — PDF possivelmente digitalizado (imagem).")
            continue

        # Seções do corpo (descarta linhas de sumário, que têm pontilhado + página)
        secoes = {}
        for secao in _quebrar_em_secoes(texto):
            if _TOC_RE.search(secao["titulo"]) or len(secao["texto"]) < 120:
                continue
            anterior = secoes.get(secao["numero"])
            if anterior is None or len(secao["texto"]) > len(anterior["texto"]):
                secoes[secao["numero"]] = secao

        mapa = _mapa_codigos_apendice(texto)
        if mapa:
            casados = 0
            for num_secao, codigos in mapa.items():
                secao = secoes.get(num_secao)
                if not secao:
                    continue
                for codigo in codigos:
                    servicos[codigo] = {
                        "titulo": secao["titulo"],
                        "descricao": secao["texto"],
                        "fonte": pdf.name,
                        "secao": num_secao,
                        "nivel": secao["nivel"],
                    }
                    casados += 1
            avisos.append(f"{pdf.name}: Apêndice A encontrado — {len(mapa)} subgrupos, "
                          f"{casados} código(s) associados ao texto da seção.")
        else:
            for secao in secoes.values():
                for codigo in set(_CODIGO_PDF_RE.findall(secao["texto"][:400])):
                    anterior = servicos.get(codigo)
                    if anterior and anterior["nivel"] >= secao["nivel"]:
                        continue
                    servicos[codigo] = {
                        "titulo": secao["titulo"], "descricao": secao["texto"],
                        "fonte": pdf.name, "secao": secao["numero"], "nivel": secao["nivel"],
                    }
            avisos.append(f"{pdf.name}: sem Apêndice A — usei a busca de códigos "
                          f"dentro das seções (associação menos confiável).")

    indice = {"assinatura": assinatura, "servicos": servicos,
              "arquivos": [p.name for p in pdfs], "avisos": avisos}
    try:
        INDICE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(INDICE_PATH, "w", encoding="utf-8") as f:
            json.dump(indice, f, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        pass
    return indice


def carregar_base_completa(forcar_reindex: bool = False) -> Tuple[dict, dict]:
    """Junta o índice dos PDFs com o base_dnit.json manual (este tem
    precedência, para corrigir o que a extração automática não pegar bem)."""
    indice = indexar_cadernos(forcar=forcar_reindex)
    manual = load_base_dnit()
    combinado = dict(indice.get("servicos", {}))
    for codigo, dados in manual.get("servicos", {}).items():
        combinado[codigo] = {**dados, "fonte": "base_dnit.json (manual)"}
    return {"servicos": combinado}, indice
