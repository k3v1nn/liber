# SPDX-License-Identifier: AGPL-3.0-only

import re

EN = {
    "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)": "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
    "Conversor EPUB": "EPUB Converter", "Livro em PDF": "PDF book", "Mangá / HQ": "Comics / manga",
    "Importe um PDF ou páginas de HQ para começar.": "Import a PDF or comic pages to get started.",
    "Importar PDF": "Import PDF", "Exportar EPUB": "Export EPUB", "Dados do livro": "Book details",
    "Dados da HQ": "Comic details", "Título": "Title", "Autor": "Author", "Idioma": "Book language",
    "Direção": "Reading direction", "Leitura da direita para a esquerda": "Read from right to left",
    "A análise sugere a estrutura; revise os títulos e a ordem dos blocos.": "The analysis suggests a structure; review headings and reading order.",
    "Blocos encontrados (selecione para corrigir)": "Detected blocks (select to edit)",
    "Página": "Page", "Tipo": "Type", "Conteúdo": "Content", "↑ Bloco": "↑ Move block",
    "↓ Bloco": "↓ Move block", "Página:": "Page:", "Bloco:": "Block:",
    "Texto do bloco selecionado": "Selected block text", "Salvar correção e atualizar prévia": "Save edit and refresh preview",
    "Selecione um bloco para ver a página original.": "Select a block to view the original page.",
    "PDF original": "Original PDF", "Prévia do texto": "Text preview",
    "Adicionar imagens": "Add images", "Adicionar pasta": "Add folder", "Adicionar PDF": "Add PDF", "Importar URL": "Import URL",
    "Escolher PDF de HQ": "Choose comic PDF", "Convertendo páginas do PDF...": "Converting PDF pages...",
    "Escolher imagem": "Choose image", "Limpar capa": "Clear cover", "Prévia da página": "Page preview",
    "Importe um PDF para escolher a capa": "Import a PDF to choose a cover",
    "Adicione páginas para escolher a capa": "Add pages to choose a cover",
    "Revise a ordem das páginas. URLs importam imagens visíveis de uma página pública; sites dinâmicos podem exigir arquivos locais.": "Review page order. URLs import visible images from a public page; dynamic sites may require local files.",
    "Selecione uma página para conferir.": "Select a page to preview.",
    "↑ Subir": "↑ Move up", "↓ Descer": "↓ Move down", "Remover": "Remove",
    "Início de capítulo": "Chapter start", "Capa": "Cover", "Usar página selecionada": "Use selected page",
    "Adicionar capa customizada": "Add custom cover", "Remover capa customizada": "Remove custom cover",
    "Capa sugerida": "Suggested cover", "Capa customizada": "Custom cover",
    "Escolher página do PDF": "Choose PDF page", "Escolher imagem de capa": "Choose cover image",
    "A imagem escolhida aparece como capa no EPUB, sem substituir uma página do livro.": "The chosen image becomes the EPUB cover without replacing a book page.",
    "Idioma da interface": "Interface language", "Pronto para começar": "Ready to start",
    "Analisando PDF...": "Analyzing PDF...", "Gerando EPUB...": "Creating EPUB...",
    "Gerando EPUB de HQ...": "Creating comic EPUB...", "Baixando imagens da página...": "Downloading page images...",
    "Escolher PDF": "Choose PDF", "Salvar EPUB": "Save EPUB", "Escolher imagens": "Choose images",
    "Escolher pasta de imagens": "Choose image folder", "Importar imagens": "Import images",
    "URL de uma imagem ou galeria pública:": "URL of a public image or gallery:",
    "Capítulo": "Chapter", "Título do capítulo que começa nesta página:": "Title of the chapter starting on this page:",
    "Parágrafo": "Paragraph", "Seção": "Section", "Nota": "Note", "Legenda": "Caption",
    "Imagem": "Image", "Ignorar": "Ignore", "Capa externa": "Outer cover", "Capa interna": "Inner cover",
    "Folha de rosto": "Title page", "Créditos": "Credits", "Dedicatória": "Dedication",
    "Epígrafe": "Epigraph", "Sumário": "Table of contents", "Bibliografia": "Bibliography",
    "Índice remissivo": "Index", "Escolha uma página ou adicione uma imagem.": "Choose a page or add an image.",
    "Editar estrutura": "Edit structure", "Páginas da HQ": "Comic pages",
}

ENGINE_MESSAGES = {
    "O PDF está protegido por senha.": "The PDF is password protected.",
    "O PDF não contém páginas.": "The PDF has no pages.",
    "A maior parte do PDF parece escaneada, e o OCR não conseguiu recuperar texto suficiente.": "Most pages appear scanned, and OCR could not recover enough text.",
    "Não foi possível extrair blocos de conteúdo deste PDF.": "No content blocks could be extracted from this PDF.",
    "Capa não identificada com segurança; a primeira página foi escolhida como sugestão.": "No clear cover was detected; the first page was suggested.",
    "Não há conteúdo extraído para exportar. Um PDF escaneado precisa de OCR.": "There is no extracted content to export. A scanned PDF needs OCR.",
    "Nenhuma seção válida foi produzida.": "No valid section was produced.",
    "Adicione páginas antes de exportar.": "Add pages before exporting.",
    "A capa selecionada não existe.": "The selected cover does not exist.",
}


def translate_engine_message(message: str, language: str) -> str:
    if language != "en":
        return message
    if message in ENGINE_MESSAGES:
        return ENGINE_MESSAGES[message]
    for pattern, replacement in (
        (r"^OCR falhou na página (\d+): (.*)$", r"OCR failed on page \1: \2"),
        (r"^OCR aplicado às páginas: (.*)$", r"OCR applied to pages: \1"),
        (r"^Páginas com pouco texto detectadas: (.*)$", r"Pages with little text detected: \1"),
        (r"^A página (\d+) do PDF tem tamanho inválido\.$", r"PDF page \1 has an invalid size."),
    ):
        if re.match(pattern, message):
            return re.sub(pattern, replacement, message)
    return message
