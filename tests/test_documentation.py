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
    actual_files = {path.name for path in OPERATIVE.iterdir() if path.is_file()}
    assert actual_files == {
        "PENDIENTES_ACTIVOS.md",
        "IMPLEMENTACIONES_REALIZADAS.md",
        "ACTUALIZACION_ACTUAL.md",
        "ESTRATEGIA_DE_PRUEBAS.md",
        "HOJA_DE_RUTA_PRE_RELEASE.md",
    }


def test_private_project_docs_root_has_only_history_map_as_file() -> None:
    actual_files = {path.name for path in PRIVATE_DOCS.iterdir() if path.is_file()}
    assert actual_files == {"HISTORIAL_DE_CAMBIOS.md"}


def test_repository_root_has_no_private_continuity_documents() -> None:
    forbidden = [
        *ROOT.glob("RELEVO_NUEVA_CONVERSACION_*.md"),
        *ROOT.glob("PUBLICATION_CHECKPOINT_*.txt"),
        *ROOT.glob("CONTINUITY_STATE*.txt"),
        *ROOT.glob("*_INSTALACION_Y_PRUEBA.md"),
        *ROOT.glob("*_INSTALACION_Y_PRUEBA.txt"),
    ]
    assert not forbidden
    assert not list(ROOT.glob("INSTALAR_*.sh"))
    assert not (ROOT / "PACKAGE_MANIFEST.json").exists()
    delivery = ROOT / "delivery"
    if (ROOT / ".git").exists():
        assert not delivery.exists()
    elif delivery.exists():
        assert (delivery / "INSTALL_1_1_0.sh").is_file()
        assert (delivery / "PACKAGE_MANIFEST.json").is_file()


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




def test_public_download_links_use_managed_release_asset() -> None:
    expected = "https://github.com/alexdcolman/archive-workbench/releases/latest/download/Archive-Workbench.zip"
    assert expected in (DOCS / "index.html").read_text(encoding="utf-8")
    assert expected in (DOCS / "instalacion.html").read_text(encoding="utf-8")
    assert expected in (ROOT / "README.md").read_text(encoding="utf-8")

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


def test_web02_current_review_and_catalog_screenshots_are_canonical() -> None:
    screenshots = DOCS / "assets" / "screenshots"
    required = {
        "CAT-03-productores-responsables.png",
        "CAT-10-organizar-documentos.png",
        "REV-01-revision-estructural.png",
        "ANN-01-edicion-anotacion.png",
        "ANN-02-anotaciones.png",
    }
    assert required <= {path.name for path in screenshots.glob("*.png")}
    assert not (screenshots / "REV-01-revisar-documentos.png").exists()
    assert not (screenshots / "REV-03-orden-estructura.png").exists()

