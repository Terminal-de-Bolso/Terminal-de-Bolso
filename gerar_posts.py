#!/usr/bin/env python3
"""
Gera uma página HTML de verdade para cada post do Terminal de Bolso.

Por quê: o Google e a prévia do WhatsApp não executam o JavaScript do
index.html direito. Com uma página por post, cada texto tem endereço próprio
(post/<id>/), título, descrição e conteúdo já prontos no HTML.

Uso (na pasta do site, onde estão index.html e posts.json):

    python3 gerar_posts.py --site https://SEU-ENDERECO

Sem --site, as páginas são geradas, mas sem canonical e sem sitemap.xml.

Precisa de uma destas bibliotecas (qualquer uma):
    sudo apt install python3-markdown-it     (recomendada)
    sudo apt install python3-markdown
"""
import argparse
import html
import json
import math
import re
import shutil
import sys
import unicodedata
from pathlib import Path

NOME_SITE = "Terminal de Bolso"
AUTOR_PADRAO = "Marcos Vinicius"
DESCRICAO_SITE = ("Guias práticos de Linux, programação, hardware e tecnologia "
                  "explicados sem enrolação. Por Marcos Vinicius.")
MARCA = "<!-- gerado por gerar_posts.py -->"
LIMITES = {"tag": 40, "titulo": 120, "texto": 20000}
MAX_POSTS = 300

GISCUS = {
    "data-repo": "Terminal-de-Bolso/Terminal-de-Bolso",
    "data-repo-id": "R_kgDOVniHSw",
    "data-category": "Announcements",
    "data-category-id": "DIC_kwDOVniHS84DKsJV",
    "data-mapping": "specific",
    "data-strict": "0",
    "data-reactions-enabled": "1",
    "data-emit-metadata": "0",
    "data-input-position": "bottom",
    "data-lang": "pt",
}

# Mesmas versões e hashes do index.html
SCRIPTS_CDN = (
    '<script src="https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@11.9.0/highlight.min.js" '
    'integrity="sha384-F/bZzf7p3Joyp5psL90p/p89AZJsndkSoGwRpXcZhleCWhd8SnRuoYo4d0yirjJp" '
    'crossorigin="anonymous" defer></script>'
)


# ---------- Mesma lógica do index.html (ids precisam ser idênticos) ----------

def limpar(valor, maximo):
    texto = "" if valor is None else str(valor)
    texto = re.sub(r"\r\n?", "\n", texto).strip()
    return texto[:maximo]


def slugificar(texto):
    s = str(texto or "").lower()
    s = unicodedata.normalize("NFD", s)
    s = re.sub(r"[\u0300-\u036f]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"^-+|-+$", "", s)[:60]
    return s or "post"


def normalizar(bruto):
    lista = bruto if isinstance(bruto, list) else (bruto.get("posts") or [])
    saida = []
    for item in lista:
        if len(saida) >= MAX_POSTS:
            break
        if not isinstance(item, dict):
            continue
        tag = limpar(item.get("tag"), LIMITES["tag"]) or "Geral"
        titulo = limpar(item.get("titulo"), LIMITES["titulo"])
        texto = limpar(item.get("texto"), LIMITES["texto"])
        data = limpar(item.get("data"), 20)
        id_ = limpar(item.get("id"), 80)
        autor = limpar(item.get("autor"), 60) or AUTOR_PADRAO
        if titulo and texto:
            saida.append({"id": id_, "tag": tag, "titulo": titulo,
                          "texto": texto, "data": data, "autor": autor})
    return saida


def atribuir_ids(posts):
    usados = set()
    for p in posts:
        base = slugificar(p["id"]) if p["id"] else slugificar(p["titulo"])
        id_, n = base, 2
        while id_ in usados:
            id_ = f"{base}-{n}"
            n += 1
        usados.add(id_)
        p["id"] = id_


def extrair_resumo(md):
    s = str(md or "")
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[.*?\]\(.*?\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.M)
    s = re.sub(r"[*_~>|-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def minutos_de_leitura(texto):
    return max(1, math.ceil(len(texto.split()) / 200))


# ---------- Markdown ----------

def criar_renderizador():
    try:
        from markdown_it import MarkdownIt
        md = MarkdownIt("commonmark", {"html": False}).enable("table")
        return md.render
    except ImportError:
        pass
    try:
        import markdown
        return lambda t: markdown.markdown(
            t, extensions=["fenced_code", "tables"], output_format="html")
    except ImportError:
        sys.exit("Falta uma biblioteca de Markdown.\n"
                 "Instale com: sudo apt install python3-markdown-it")


def e(texto):
    return html.escape(str(texto), quote=True)


def tratar_html(corpo):
    """Links externos, blocos de código com barra e ids nos títulos."""
    corpo = corpo.replace('<a href="http',
                          '<a target="_blank" rel="noopener noreferrer" href="http')

    corpo = re.sub(r'<pre><code(?: class="language-([a-z0-9_-]+)")?>.*?</code></pre>',
                   lambda m: bloco_com_lang(m), corpo, flags=re.S)

    titulos = []

    def titulo(m):
        idx = len(titulos)
        texto = html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        id_ = f"sec-{idx}-{slugificar(texto)}"
        titulos.append((m.group(1), id_, texto))
        return f'<h{m.group(1)} id="{id_}">{m.group(2)}</h{m.group(1)}>'

    corpo = re.sub(r"<h([23])>(.*?)</h\1>", titulo, corpo, flags=re.S)
    return corpo, titulos


def bloco_com_lang(m):
    lang = re.search(r'class="language-([a-z0-9_-]+)"', m.group(0))
    nome = lang.group(1) if lang else "código"
    return ('<div class="code-wrap"><div class="code-bar"><span>' + e(nome)
            + '</span><button class="cp-code" type="button">Copiar</button></div>'
            + m.group(0) + '</div>')


def sumario(titulos):
    if len(titulos) < 2:
        return ""
    itens = "".join(
        f'<li class="{"toc-h3" if nivel == "3" else ""}"><a href="#{id_}">{e(txt)}</a></li>'
        for nivel, id_, txt in titulos)
    return (f'<details class="toc" open><summary>Neste artigo</summary>'
            f'<ul>{itens}</ul></details>')


# ---------- Página ----------

JS_PAGINA = r"""
(function () {
  var raiz = document.documentElement;
  var botao = document.getElementById('tema');
  function atual() {
    if (raiz.dataset.theme === 'dark' || raiz.dataset.theme === 'light') return raiz.dataset.theme;
    return (window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }
  function atualizarBotao() {
    var modo = atual();
    botao.textContent = modo === 'dark' ? '☀ Claro' : '☾ Escuro';
    botao.setAttribute('aria-label', modo === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro');
  }
  function temaComentarios() {
    var f = document.querySelector('iframe.giscus-frame');
    if (f && f.contentWindow) {
      f.contentWindow.postMessage({ giscus: { setConfig: { theme: atual() } } }, 'https://giscus.app');
    }
  }
  atualizarBotao();
  botao.addEventListener('click', function () {
    var novo = atual() === 'dark' ? 'light' : 'dark';
    raiz.dataset.theme = novo;
    try { localStorage.setItem('tema', novo); } catch (e) {}
    atualizarBotao();
    temaComentarios();
  });

  var menuBtn = document.getElementById('menu-btn');
  var nav = document.getElementById('menu-principal');
  menuBtn.addEventListener('click', function () {
    var aberto = nav.classList.toggle('aberto');
    menuBtn.setAttribute('aria-expanded', String(aberto));
  });

  document.addEventListener('click', function (ev) {
    var b = ev.target.closest ? ev.target.closest('.cp-code') : null;
    if (!b) return;
    var pre = b.closest('.code-wrap').querySelector('pre');
    navigator.clipboard.writeText(pre.textContent).then(function () {
      b.textContent = 'Copiado!';
      setTimeout(function () { b.textContent = 'Copiar'; }, 2000);
    }, function () {});
  });

  var url = location.href.split('#')[0];
  var titulo = document.title;
  var caixa = document.getElementById('compartilhar');
  caixa.appendChild(Object.assign(document.createElement('span'), { textContent: 'Compartilhar:' }));
  var copiar = Object.assign(document.createElement('button'), { className: 'share-btn', type: 'button', textContent: 'Copiar link' });
  copiar.addEventListener('click', function () {
    navigator.clipboard.writeText(url).then(function () {
      copiar.textContent = 'Copiado!';
      setTimeout(function () { copiar.textContent = 'Copiar link'; }, 2000);
    }, function () {});
  });
  caixa.appendChild(copiar);
  [
    ['WhatsApp', 'https://wa.me/?text=' + encodeURIComponent(titulo + ' ' + url)],
    ['X / Twitter', 'https://twitter.com/intent/tweet?text=' + encodeURIComponent(titulo) + '&url=' + encodeURIComponent(url)],
    ['LinkedIn', 'https://www.linkedin.com/sharing/share-offsite/?url=' + encodeURIComponent(url)]
  ].forEach(function (r) {
    var a = Object.assign(document.createElement('a'), { className: 'share-btn', textContent: r[0], href: r[1], target: '_blank', rel: 'noopener noreferrer' });
    caixa.appendChild(a);
  });

  window.addEventListener('load', function () {
    if (window.hljs) {
      document.querySelectorAll('pre code').forEach(function (c) { window.hljs.highlightElement(c); });
    }
  });

  var s = document.createElement('script');
  s.src = 'https://giscus.app/client.js';
  var cfg = __GISCUS__;
  cfg['data-term'] = __TERM__;
  cfg['data-theme'] = atual();
  for (var k in cfg) s.setAttribute(k, cfg[k]);
  s.crossOrigin = 'anonymous';
  s.async = true;
  document.getElementById('comentarios').appendChild(s);
})();
"""


def pagina(post, idx, posts, css, corpo, titulos, site):
    titulo_pag = f"{post['titulo']} — {NOME_SITE}"
    descricao = extrair_resumo(post["texto"])[:155] + "..."
    url = f"{site}/post/{post['id']}/" if site else ""

    meta_data = [f"Por {post['autor']}"]
    if post["data"]:
        meta_data.append(post["data"])
    meta_data.append(f"{minutos_de_leitura(post['texto'])} min de leitura")

    ld = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": post["titulo"],
        "description": descricao,
        "author": {"@type": "Person", "name": post["autor"]},
        "keywords": post["tag"],
    }
    if re.match(r"^\d{4}-\d{2}-\d{2}", post["data"]):
        ld["datePublished"] = post["data"]
    if url:
        ld["mainEntityOfPage"] = url
    ld_json = json.dumps(ld, ensure_ascii=False).replace("<", "\\u003c")

    anterior = posts[idx + 1] if idx + 1 < len(posts) else None
    proximo = posts[idx - 1] if idx - 1 >= 0 else None
    nav_posts = ""
    if anterior or proximo:
        cards = ""
        if anterior:
            cards += (f'<a class="nav-post-card" href="../{e(anterior["id"])}/">'
                      f'<small>← Post anterior</small><span>{e(anterior["titulo"])}</span></a>')
        if proximo:
            cards += (f'<a class="nav-post-card" href="../{e(proximo["id"])}/">'
                      f'<small>Próximo post →</small><span>{e(proximo["titulo"])}</span></a>')
        nav_posts = f'<div class="nav-posts">{cards}</div>'

    relacionados = [p for p in posts
                    if p["id"] != post["id"] and p["tag"].lower() == post["tag"].lower()][:2]
    rel_html = ""
    if relacionados:
        cards = ""
        for r in relacionados:
            pre = (r["data"] + " · ") if r["data"] else ""
            cards += (f'<a class="rel-card" href="../{e(r["id"])}/">'
                      f'<small>{e(pre)}{minutos_de_leitura(r["texto"])} min</small>'
                      f'<strong>{e(r["titulo"])}</strong></a>')
        rel_html = (f'<div class="relacionados"><h3>Leia também sobre {e(post["tag"])}</h3>'
                    f'<div class="relacionados-grid">{cards}</div></div>')

    cabecalho_seo = (
        f'<meta name="description" content="{e(descricao)}">\n'
        f'<meta name="author" content="{e(post["autor"])}">\n'
        '<meta name="robots" content="index, follow">\n'
        '<meta property="og:type" content="article">\n'
        f'<meta property="og:site_name" content="{NOME_SITE}">\n'
        '<meta property="og:locale" content="pt_BR">\n'
        f'<meta property="og:title" content="{e(titulo_pag)}">\n'
        f'<meta property="og:description" content="{e(descricao)}">\n'
        '<meta name="twitter:card" content="summary">\n'
        f'<meta name="twitter:title" content="{e(titulo_pag)}">\n'
        f'<meta name="twitter:description" content="{e(descricao)}">\n'
    )
    if url:
        cabecalho_seo += (f'<link rel="canonical" href="{e(url)}">\n'
                          f'<meta property="og:url" content="{e(url)}">\n')

    js = (JS_PAGINA
          .replace("__GISCUS__", json.dumps(GISCUS))
          .replace("__TERM__", json.dumps(post["id"])))

    return f"""<!DOCTYPE html>
{MARCA}
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f1115" media="(prefers-color-scheme: dark)">
<title>{e(titulo_pag)}</title>
{cabecalho_seo}<link rel="icon" type="image/png" href="../../favicon.png">
<script type="application/ld+json">{ld_json}</script>
{SCRIPTS_CDN}
<style>
{css}
</style>
<script>
try {{
  var temaSalvo = localStorage.getItem('tema');
  if (temaSalvo === 'dark' || temaSalvo === 'light') {{ document.documentElement.dataset.theme = temaSalvo; }}
}} catch (e) {{}}
</script>
</head>
<body>

<a class="skip-link" href="#conteudo-principal">Pular para o conteúdo</a>

<header>
  <div class="wrap">
    <a class="logo" href="../../">Terminal <span>de Bolso</span></a>
    <div class="nav-acoes">
      <button id="tema" type="button" aria-label="Alternar tema">Tema</button>
      <button id="menu-btn" type="button" aria-expanded="false" aria-controls="menu-principal">Menu</button>
    </div>
    <nav id="menu-principal" aria-label="Menu principal">
      <a href="../../#posts">Posts</a>
      <a href="../../#mais">Arquivo</a>
      <a href="../../#terminal">Terminal</a>
      <a href="../../#sobre">Sobre</a>
      <a href="../../#contato">Contato</a>
    </nav>
  </div>
</header>

<main id="conteudo-principal" class="wrap">
  <nav class="breadcrumb" aria-label="Navegação estrutural">
    <a href="../../#posts">Início</a><span>›</span><span>{e(post["tag"])}</span><span>›</span><span>{e(post["titulo"])}</span>
  </nav>

  <article class="post-completo">
    <div class="linha">
      <span class="tag">{e(post["tag"])}</span>
      <span class="meta">{e(" · ".join(meta_data))}</span>
    </div>
    <h1 class="titulo-post">{e(post["titulo"])}</h1>
    {sumario(titulos)}
    <div class="conteudo-markdown">
{corpo}
    </div>

    <div class="compartilhar" id="compartilhar"></div>

    <div class="autor-box">
      <div class="autor-avatar" aria-hidden="true">MV</div>
      <div class="autor-info">
        <strong>Escrito por {e(post["autor"])}</strong>
        <p>Autor do {NOME_SITE}. Escrevo guias práticos sobre Linux, código aberto, programação e hardware.</p>
      </div>
    </div>

    {nav_posts}
    {rel_html}

    <div class="acoes-post">
      <a class="voltar" href="../../#posts">← Voltar para os posts</a>
      <a class="voltar" href="../../#mais">Ver todos os posts →</a>
    </div>

    <section class="comentarios" id="comentarios"><h3>Comentários</h3></section>
  </article>
</main>

<footer>
  <div class="wrap footer-grid">
    <div>© 2026 {NOME_SITE} · Por {AUTOR_PADRAO}. Feito com software livre em mente.</div>
    <div class="footer-links">
      <a href="../../#posts">Início</a>
      <a href="../../#mais">Arquivo</a>
      <a href="../../#privacidade">Privacidade</a>
      <a href="https://github.com/Terminal-de-Bolso/Terminal-de-Bolso" target="_blank" rel="noopener noreferrer">GitHub</a>
    </div>
  </div>
</footer>

<script>{js}</script>
</body>
</html>
"""


# ---------- Principal ----------

def main():
    ap = argparse.ArgumentParser(description="Gera uma página estática por post.")
    ap.add_argument("--site", default="", help="endereço do site, ex.: https://usuario.github.io/repo")
    ap.add_argument("--posts", default="posts.json")
    ap.add_argument("--index", default="index.html")
    ap.add_argument("--saida", default=".")
    args = ap.parse_args()

    site = args.site.strip().rstrip("/")
    raiz = Path(args.saida)

    try:
        dados = json.loads(Path(args.posts).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"Não achei {args.posts}. Rode na pasta do site.")
    except json.JSONDecodeError as erro:
        sys.exit(f"{args.posts} tem erro de JSON: {erro}")

    try:
        indice = Path(args.index).read_text(encoding="utf-8")
    except FileNotFoundError:
        sys.exit(f"Não achei {args.index}. Rode na pasta do site.")
    achou = re.search(r"<style>(.*?)</style>", indice, flags=re.S)
    if not achou:
        sys.exit("Não achei o bloco <style> no index.html.")
    css = achou.group(1).strip()

    posts = normalizar(dados)
    posts.reverse()  # mesma ordem do index.html: mais novo primeiro
    atribuir_ids(posts)

    render = criar_renderizador()

    # Apaga só páginas geradas antes por este script (pelo marcador)
    pasta_posts = raiz / "post"
    if pasta_posts.is_dir():
        for sub in pasta_posts.iterdir():
            arq = sub / "index.html"
            if arq.is_file() and MARCA in arq.read_text(encoding="utf-8", errors="ignore")[:200]:
                shutil.rmtree(sub)

    for idx, post in enumerate(posts):
        corpo, titulos = tratar_html(render(post["texto"]))
        destino = pasta_posts / post["id"]
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "index.html").write_text(
            pagina(post, idx, posts, css, corpo, titulos, site), encoding="utf-8")

    print(f"{len(posts)} página(s) gerada(s) em {pasta_posts}/")

    if site:
        linhas = ['<?xml version="1.0" encoding="UTF-8"?>',
                  '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
                  f"  <url><loc>{e(site)}/</loc></url>"]
        for p in posts:
            lm = ""
            if re.match(r"^\d{4}-\d{2}-\d{2}$", p["data"]):
                lm = f"<lastmod>{p['data']}</lastmod>"
            linhas.append(f"  <url><loc>{e(site)}/post/{e(p['id'])}/</loc>{lm}</url>")
        linhas.append("</urlset>")
        (raiz / "sitemap.xml").write_text("\n".join(linhas) + "\n", encoding="utf-8")
        print("sitemap.xml gerado")

        robots = raiz / "robots.txt"
        if not robots.exists():
            robots.write_text(f"User-agent: *\nAllow: /\n\nSitemap: {site}/sitemap.xml\n",
                              encoding="utf-8")
            print("robots.txt criado")
    else:
        print("Dica: use --site https://SEU-ENDERECO para gerar também canonical e sitemap.xml")


if __name__ == "__main__":
    main()
