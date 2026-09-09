from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
PRIVATE_DOCS = ROOT / ".assistant" / "project_docs"
OPERATIVE = PRIVATE_DOCS / "operativos"


class _LocalResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("href", "src"):
            value = values.get(key)
            if value:
                self.targets.append(value)


def test_docs_root_is_public_only_and_private_documents_are_unique() -> None:
    root_files = {path.name for path in DOCS.iterdir() if path.is_file()}
    assert {"index.html", "desarrollo.html", ".nojekyll"}.issubset(root_files)
    assert not list(DOCS.rglob("*.md"))
    assert not list(DOCS.rglob("*.txt"))
    assert len(list(PRIVATE_DOCS.rglob("PENDIENTES_ACTIVOS.md"))) == 1
    assert len(list(PRIVATE_DOCS.rglob("IMPLEMENTACIONES_REALIZADAS.md"))) == 1


def test_assistant_continuity_documents_exist() -> None:
    assistant = ROOT / ".assistant"
    if not assistant.is_dir():
        return
    required = {
        "00_LEER_PRIMERO.md",
        "00_CHECKLIST_CAMBIOS.md",
        "01_INTERACCION_Y_GUIADO.md",
        "02_POLITICA_DOCUMENTAL.md",
        "03_POLITICA_DE_PRUEBAS.md",
        "04_CONTINUIDAD_DEL_PROYECTO.md",
        "05_CRITERIOS_INTERFAZ.md",
        "05_FORMULARIOS_STREAMLIT.md",
        "06_RELEVO_NUEVA_CONVERSACION.md",
        "07_SEGURIDAD_ARCHIVOS_Y_REPOSITORIO.md",
    }
    assert required.issubset({path.name for path in assistant.glob("*.md")})
    assert (ROOT / ".gitignore").is_file()


def test_operational_docs_contain_only_canonical_documents() -> None:
    actual = {path.name for path in OPERATIVE.iterdir() if path.is_file() or path.is_dir()}
    assert {
        "PENDIENTES_ACTIVOS.md",
        "IMPLEMENTACIONES_REALIZADAS.md",
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "HOJA_DE_RUTA_PRE_RELEASE.md",
    }.issubset(actual)


def test_public_documentation_does_not_contain_private_directories() -> None:
    assert not (DOCS / "operativos").exists()
    assert not (DOCS / "referencia").exists()
    assert not (DOCS / "historico").exists()


def test_public_site_required_pages_exist() -> None:
    required = {
        "index.html", "instalacion.html", "tutorial.html", "catalogo.html",
        "procesamiento.html", "trabajo.html", "revision.html", "entidades.html",
        "busquedas.html", "relaciones.html", "audiovisual.html", "exportacion.html",
        "intercambio.html", "resguardo.html", "conceptos.html", "referencia.html",
        "desarrollo.html", "problemas.html", "404.html",
    }
    assert required.issubset({path.name for path in DOCS.glob("*.html")})


def test_public_site_local_resources_resolve() -> None:
    for html in DOCS.glob("*.html"):
        parser = _LocalResourceParser()
        parser.feed(html.read_text(encoding="utf-8"))
        for target in parser.targets:
            parsed = urlsplit(target)
            if parsed.scheme or target.startswith(("#", "mailto:")) or not parsed.path:
                continue
            resolved = (html.parent / parsed.path).resolve()
            assert resolved.exists(), f"broken local resource in {html.name}: {target}"


def test_public_diagram_files_exist() -> None:
    diagrams = DOCS / "assets" / "diagrams"
    required = {
        "flujo-general.svg",
        "trazabilidad-texto.svg",
        "arquitectura-local.svg",
        "intercambio.svg",
    }
    assert required.issubset({path.name for path in diagrams.glob("*.svg")})
