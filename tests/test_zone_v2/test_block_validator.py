"""Tests for block-level code construct validator."""
from docs.experiments.prompt_analysis.s4_zone_detection.v2.block_validator import count_code_constructs, has_math_notation


class TestCodeBlocks:
    def test_python_function(self):
        block = "def process(data):\n    result = []\n    for item in data:\n        result.append(item)\n    return result"
        assert count_code_constructs(block) >= 3  # func_def + assignment + control_flow + return

    def test_javascript_class(self):
        block = "class MyApp {\n  constructor() {\n    this.data = [];\n  }\n  render() {\n    return this.data;\n  }\n}"
        assert count_code_constructs(block) >= 3  # class_def + assignment + return + semicolon

    def test_import_and_assignment(self):
        block = "import json\n\ndata = json.loads(text)\nresult = process(data)"
        assert count_code_constructs(block) >= 3  # import + assignment + method_chain

    def test_c_function(self):
        block = "int main() {\n    int x = 0;\n    printf(\"hello\");\n    return 0;\n}"
        assert count_code_constructs(block) >= 3  # assignment + return + semicolon

    def test_short_verilog(self):
        """Short Verilog — should have constructs from assignments + semicolons."""
        block = "reg spi_clk_r = 1'b0;\nwire spi_clkp = spi_clk_i&&(spi_clk_r==1'b0);\nalways @(posedge clk)begin\n    spi_clk_r <= spi_clk_i;\nend"
        assert count_code_constructs(block) >= 2  # assignment + semicolon

    def test_decorator(self):
        block = "@app.route('/api')\ndef handler(request):\n    return response"
        assert count_code_constructs(block) >= 3  # decorator + func_def + return

    def test_bare_function_calls(self):
        """Function calls without assignment — dict(set()), smr_init()."""
        block = "dict(set())\ndefaultdict(set)\ndict({})"
        assert count_code_constructs(block) >= 1  # func_call

    def test_sql_create_table(self):
        block = "CREATE TABLE client (\nid INT PRIMARY KEY,\nname VARCHAR(50)\n);"
        assert count_code_constructs(block) >= 1  # sql

    def test_sql_select(self):
        block = "SELECT u.name, o.total\nFROM users u\nJOIN orders o ON u.id = o.uid\nWHERE o.date > '2024-01-01'"
        assert count_code_constructs(block) >= 1  # sql

    def test_r_assignment(self):
        block = 'RW_idx <- which(grepl("RW", Data$Positions))\nST_idx <- which(grepl("ST", Data$Positions))'
        assert count_code_constructs(block) >= 2  # r_assignment + func_call


class TestNonCodeBlocks:
    def test_midjourney_template(self):
        """Midjourney template — zero code constructs."""
        block = "\n".join([
            "Structure:",
            "[1] = a concept",
            "[2] = a detailed description of [1]",
            "[3] = a detailed description of the scene",
            "[4] = a detailed description of compositions",
            "[5] = mood, feelings, and atmosphere",
            "[6] = A style (e.g. photography, painting)",
        ])
        assert count_code_constructs(block) == 0

    def test_basketball_stats(self):
        """Sports stats — zero code constructs."""
        block = "\n".join([
            "Milwaukee Bucks plays at home",
            "Points per game: 112.5",
            "Rebounds per game: 44.2",
            "Assists per game: 25.8",
            "Field goal percentage: 47.3%",
        ])
        assert count_code_constructs(block) == 0

    def test_latex_math(self):
        """LaTeX formulas — zero code constructs."""
        block = "\n".join([
            r"\left( 2^x \right)^2 \cdot \frac{2^7}{2^5} = 16",
            r"2^{2x} \cdot 2^{7-5} = 16",
            r"2^{2x} \cdot 2^2 = 16",
            r"2^{2x + 2} = 2^4",
        ])
        assert count_code_constructs(block) == 0

    def test_game_level_list(self):
        """Game level list — zero code constructs."""
        block = "\n".join([
            "AT HELL'S GATE LEVEL LIST",
            "{0:0} A Burning Memory",
            "{0:1} The Outskirts",
            "{0:2} Into The Fire",
        ])
        assert count_code_constructs(block) == 0

    def test_song_lyrics(self):
        """Song lyrics with parens — zero code constructs."""
        block = "\n".join([
            '("No, no, no quiero saber todo lo que hice ayer',
            "Creo que perdí la cabeza",
            "Eso de beber tanto alcohol me hace perder dirección",
            "A veces uno ya no piensa",
        ])
        assert count_code_constructs(block) == 0

    def test_prose_with_keywords(self):
        """English prose containing programming words — zero constructs."""
        block = "\n".join([
            "As a prompt generator for a generative AI called Midjourney,",
            "you will create image prompts for the AI to visualize.",
            "The function of this tool is to generate creative descriptions",
            "for each concept provided by the user.",
        ])
        assert count_code_constructs(block) == 0


class TestMathNotation:
    def test_latex_commands(self):
        """LaTeX with \\frac, \\left — detected as math."""
        block = r"\left( 2^x \right)^2 \cdot \frac{2^7}{2^5} = 16"
        assert has_math_notation(block) is True

    def test_unicode_math_symbols(self):
        """Unicode Greek letters and math operators — detected as math."""
        block = "z_i=e^(λ_i Δt)⟹λ_i=(ln⁡(z_i ))/Δt"
        assert has_math_notation(block) is True

    def test_stats_notation(self):
        """Statistical notation with μ, Σ, π — detected as math."""
        block = "Mean ages: E(U) = 40, E(V) = 50\nVariances: Var(U) = 100\nΣ is the covariance matrix"
        assert has_math_notation(block) is True

    def test_real_code_no_math(self):
        """Real Python code — NOT detected as math."""
        block = "def process(data):\n    result = []\n    for item in data:\n        result.append(item)\n    return result"
        assert has_math_notation(block) is False

    def test_real_code_with_comments(self):
        """Code with comments mentioning math — NOT math (no LaTeX/unicode)."""
        block = "# compute the sum of squares\nresult = sum(x**2 for x in data)\nreturn result"
        assert has_math_notation(block) is False
