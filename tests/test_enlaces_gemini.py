"""Gemini mete formato de enlace dentro del cuerpo de las herramientas.

Verificado en vivo contra la cuenta real: si el modelo escribe

    <tool name="write_file" path="a.js">const API = "https://api.x.com/v1";</tool>

lo que llega por el stream es

    const API = "[https://api.x.com/v1](https://api.x.com/v1)";

es decir, el archivo se escribiría corrupto. Hay que deshacerlo, pero SIN
romper los enlaces markdown de verdad (los de un README, por ejemplo).
"""
from mgm.protocol import ToolCallEvent, XMLToolParser
from mgm.protocol.xml_parser import desenlazar


class TestDesenlazar:
    def test_etiqueta_igual_a_la_url_se_desenvuelve(self):
        assert desenlazar("[https://x.com/v1](https://x.com/v1)") == "https://x.com/v1"

    def test_etiqueta_es_la_url_sin_esquema(self):
        assert desenlazar("[x.com/v1](https://x.com/v1)") == "x.com/v1"

    def test_un_enlace_markdown_de_verdad_se_respeta(self):
        texto = "Mira la [documentación](https://x.com/docs) para más."
        assert desenlazar(texto) == texto

    def test_respeta_el_texto_alrededor(self):
        crudo = 'const API = "[https://x.com](https://x.com)";\nconst N = 1;'
        assert desenlazar(crudo) == 'const API = "https://x.com";\nconst N = 1;'

    def test_varios_en_la_misma_linea(self):
        crudo = "[a.com](https://a.com) y [b.com](https://b.com)"
        assert desenlazar(crudo) == "a.com y b.com"

    def test_texto_sin_enlaces_no_cambia(self):
        assert desenlazar("hola mundo") == "hola mundo"


class TestParserLimpiaElCuerpo:
    def _llamada(self, texto: str) -> ToolCallEvent:
        parser = XMLToolParser()
        eventos = list(parser.feed(texto)) + list(parser.flush())
        return next(e for e in eventos if isinstance(e, ToolCallEvent))

    def test_el_cuerpo_llega_sin_el_enlace_postizo(self):
        evento = self._llamada(
            '<tool name="write_file" path="a.js">'
            'const API = "[https://api.x.com](https://api.x.com)";</tool>'
        )
        assert evento.body == 'const API = "https://api.x.com";'

    def test_tambien_limpia_los_atributos(self):
        evento = self._llamada(
            '<tool name="bash" url="[x.com](https://x.com)">echo hola</tool>'
        )
        assert evento.attrs["url"] == "x.com"
