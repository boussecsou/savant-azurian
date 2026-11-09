import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "./markdown";

const html = (text: string) => renderToStaticMarkup(<Markdown text={text} />);

describe("Markdown", () => {
  it("renders paragraphs, bold, code and line breaks", () => {
    expect(html("Un **gras** et `code`\nligne 2\n\nSuite")).toBe(
      '<div class="md"><p>Un <strong>gras</strong> et <code>code</code><br/>ligne 2</p><p>Suite</p></div>',
    );
  });

  it("renders headings down to h4, and folds deeper levels into h4", () => {
    const out = html("# Un\n\n## Deux\n\n### Trois\n\n#### Quatre\n\n##### Cinq");
    expect(out).toContain("<h1>Un</h1>");
    expect(out).toContain("<h2>Deux</h2>");
    expect(out).toContain("<h3>Trois</h3>");
    expect(out).toContain("<h4>Quatre</h4>");
    expect(out).toContain("<h4>Cinq</h4>");
    expect(out).not.toContain("<h5>");
  });

  it("renders italic and strikethrough, including nested emphasis", () => {
    expect(html("Une *pente* et ~~rayé~~")).toContain("<em>pente</em> et <del>rayé</del>");
    expect(html("**gras avec *italique***")).toContain("<strong>gras avec <em>italique</em></strong>");
  });

  it("keeps underscores inside words literal", () => {
    expect(html("notion_query_data_sources")).not.toContain("<em>");
    expect(html("notion_query_data_sources")).toContain("notion_query_data_sources");
  });

  it("renders bullet and numbered lists", () => {
    expect(html("- a\n- b")).toBe('<div class="md"><ul><li><span class="li-text">a</span></li><li><span class="li-text">b</span></li></ul></div>');
    expect(html("1. a\n2) b")).toContain("<ol><li>");
  });

  it("renders nested lists", () => {
    const out = html("- parent\n  - enfant\n  - autre\n- suivant");
    expect(out).toContain('<li><span class="li-text">parent</span><ul><li>');
    expect(out).toContain("enfant");
    expect(out).toContain("suivant");
  });

  it("renders task lists", () => {
    const out = html("- [x] fait\n- [ ] à faire");
    expect(out).toContain('class="task-list"');
    expect(out).toContain('type="checkbox"');
    expect(out).toContain("fait");
    expect(out).toContain("à faire");
  });

  it("renders a GFM table with alignment", () => {
    const out = html("| Nom | État |\n|:----|-----:|\n| Agent | prêt |\n| BFF | en ligne |");
    expect(out).toContain("<table>");
    expect(out).toContain('<th scope="col" style="text-align:left">Nom</th>');
    expect(out).toContain('<td style="text-align:right">prêt</td>');
    expect(out).toContain("en ligne");
  });

  it("renders blockquotes and horizontal rules", () => {
    expect(html("> une citation")).toContain("<blockquote><p>une citation</p></blockquote>");
    expect(html("haut\n\n---\n\nbas")).toContain("<hr/>");
  });

  it("renders fenced code with a language label and a copy button", () => {
    const out = html("```ts\nconst a = 1;\nconst b = 2;\n```");
    expect(out).toContain('<span class="code-lang">ts</span>');
    expect(out).toContain('<button type="button" class="code-copy">Copy</button>');
    expect(out).toContain("<pre><code>const a = 1;\nconst b = 2;</code></pre>");
  });

  it("keeps an unclosed fence as code instead of throwing", () => {
    const out = html("Avant\n\n```python\nprint('bonjour')\n");
    expect(out).toContain('<span class="code-lang">python</span>');
    expect(out).toContain("print(&#x27;bonjour&#x27;)");
  });

  it("opens links safely in a new tab", () => {
    expect(html("[Connecter Notion](https://mcp.notion.com/authorize?x=1)")).toContain(
      '<a href="https://mcp.notion.com/authorize?x=1" target="_blank" rel="noopener noreferrer">Connecter Notion</a>',
    );
  });

  it("links bare addresses without their trailing punctuation", () => {
    const out = html("Voir https://example.com/page.");
    expect(out).toContain('href="https://example.com/page"');
    expect(out).toContain("</a>.");
  });

  it("never turns message text into markup", () => {
    const out = html('<script>alert(1)</script> <img src=x onerror=alert(1)>');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;script&gt;");
  });

  it("refuses non-http links", () => {
    const out = html("[clic](javascript:alert(1)) [x](data:text/html,hi) [y](//evil.example)");
    expect(out).not.toContain("<a ");
    expect(out).toContain("javascript:alert(1)");
  });

  it("survives the half-written Markdown of a streaming reply", () => {
    expect(() => html("**gras inachevé")).not.toThrow();
    expect(html("**gras inachevé")).toContain("**gras inachevé");
    expect(() => html("| a | b |")).not.toThrow();
    expect(html("| a | b |")).toContain("| a | b |");
    expect(() => html("```")).not.toThrow();
    expect(() => html("[lien](http")).not.toThrow();
    expect(html("[lien](http")).toContain("[lien](http");
  });
});
