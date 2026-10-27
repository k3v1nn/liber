# SPDX-License-Identifier: AGPL-3.0-only

import re

EN = {
    # Opening screen
    "Converta PDF, mangá": "Turn PDFs, manga", "e HQ em": "and comics into",
    "Revise capítulos, capa e ordem das páginas antes de gerar o arquivo. Tudo no seu computador.": "Review chapters, cover and page order before creating the file. Everything stays on your computer.",
    "ou arraste um PDF, imagens ou uma pasta para a janela": "or drop a PDF, images or a folder onto the window",
    "Últimos EPUBs · clique para abrir a pasta": "Recent EPUBs · click to open the folder",
    "Sua estante começa aqui": "Your shelf starts here", "Voltar ao início": "Back to start",
    "Livro em PDF": "PDF book", "Mangá / HQ": "Comics / manga",
    # Toolbar and footer
    "Importe um PDF ou páginas de HQ para começar.": "Import a PDF or comic pages to get started.",
    "Importar PDF": "Import PDF", "Gerar EPUB": "Create EPUB", "Cancelar": "Cancel", "Adicionar": "Add",
    "Adicionar imagens": "Add images", "Adicionar pasta": "Add folder", "Adicionar PDF": "Add PDF", "Importar URL": "Import URL",
    "Imagens": "Images", "Pasta": "Folder", "PDF de HQ": "Comic PDF", "URL pública": "Public URL",
    "Importar URL — cole um ou vários links (um por linha); as imagens somam-se às páginas atuais.": "Import URL — paste one or more links (one per line); the images are added to the current pages.",
    "Idioma da interface": "Interface language", "Pronto para começar": "Ready to start",
    "Importe um PDF para poder exportar.": "Import a PDF to be able to export.",
    "Adicione páginas para poder exportar.": "Add pages to be able to export.",
    "Este PDF não tem blocos para exportar.": "This PDF has no blocks to export.",
    "Aguarde a tarefa atual terminar.": "Wait for the current task to finish.",
    "{name} · {pages} páginas": "{name} · {pages} pages",
    "{pages} páginas · {chapters} capítulos": "{pages} pages · {chapters} chapters",
    # Empty states
    "Nenhum PDF aberto": "No PDF open",
    "Importe um PDF para revisar capítulos, capa e texto antes de gerar o EPUB.": "Import a PDF to review chapters, cover and text before creating the EPUB.",
    "ou arraste o arquivo para a janela": "or drop the file onto the window",
    "Nenhuma página ainda": "No pages yet",
    "Adicione imagens, uma pasta, um PDF de HQ ou uma URL pública para montar a HQ.": "Add images, a folder, a comic PDF or a public URL to build the comic.",
    "Você pode juntar vários links, pastas e PDFs: todas as páginas entram no mesmo EPUB, na ordem que você revisar.": "You can mix several links, folders and PDFs: every page lands in the same EPUB, in the order you review.",
    # Book details and cover
    "Livro": "Book", "HQ": "Comic", "Título": "Title", "Autor": "Author", "Idioma": "Book language",
    "Leitura da direita para a esquerda": "Read from right to left",
    "← direita para a esquerda": "← right to left", "esquerda para a direita →": "left to right →",
    "Capa": "Cover", "Escolher imagem": "Choose image", "Limpar capa": "Clear cover",
    "Capa customizada": "Custom cover", "Escolher página do PDF": "Choose PDF page", "Escolher imagem de capa": "Choose cover image",
    "Importe um PDF para escolher a capa": "Import a PDF to choose a cover",
    "Adicione páginas para escolher a capa": "Add pages to choose a cover",
    "A análise sugere a estrutura; revise os títulos e a ordem dos blocos.": "The analysis suggests a structure; review headings and reading order.",
    "Análise concluída. Revise a estrutura antes de exportar.": "Analysis complete. Review the structure before exporting.",
    "Avisos da análise": "Analysis notes",
    # PDF structure and editor
    "Estrutura": "Structure", "Estrutura do livro": "Book structure",
    "Tudo": "All", "Capítulos": "Chapters", "Notas": "Notes", "Ignorados": "Ignored", "Ignorado": "Ignored",
    "Nenhum bloco deste tipo neste PDF.": "No block of this type in this PDF.", "Mostrar tudo": "Show all",
    "Prévia": "Preview", "Prévia do texto": "Text preview", "PDF original": "Original PDF",
    "Selecione um bloco para ver a página original.": "Select a block to view the original page.",
    "Página": "Page", "Tipo": "Type", "Bloco": "Block", "Aplicar correção": "Apply edit",
    "Texto do bloco selecionado": "Selected block text",
    "Subir bloco": "Move block up", "Descer bloco": "Move block down",
    "Edição não aplicada": "Edit not applied",
    "Correção salva no projeto atual.": "Edit saved in the current project.",
    "Correção aplicada ao bloco {number}.": "Edit applied to block {number}.",
    "Reordene blocos dentro da mesma página.": "Move blocks within the same page.",
    "Parágrafo": "Paragraph", "Seção": "Section", "Nota": "Note", "Legenda": "Caption",
    "Imagem": "Image", "Ignorar": "Ignore", "Capítulo": "Chapter",
    "Capa externa": "Outer cover", "Capa interna": "Inner cover",
    "Folha de rosto": "Title page", "Créditos": "Credits", "Dedicatória": "Dedication",
    "Epígrafe": "Epigraph", "Sumário": "Table of contents", "Bibliografia": "Bibliography",
    "Índice remissivo": "Index", "Conteúdo": "Content",
    "[imagem]": "[image]", "Imagem da página {page}": "Image on page {page}",
    "{chapters} capítulos · {blocks} blocos": "{chapters} chapters · {blocks} blocks",
    "PDF analisado: {pages} páginas, {blocks} blocos.": "PDF analyzed: {pages} pages, {blocks} blocks.",
    "Este PDF parece escaneado e o OCR não recuperou texto suficiente. Confira as páginas antes de exportar.": "This PDF appears scanned and OCR did not recover enough text. Review the pages before exporting.",
    "Importe um PDF primeiro.": "Import a PDF first.",
    # Comic pages
    "Páginas": "Pages", "Páginas da HQ": "Comic pages", "Prévia da página": "Page preview",
    "Selecione uma página para conferir.": "Select a page to preview.",
    "Mover para trás": "Move back", "Mover para frente": "Move forward", "Usar como capa": "Use as cover",
    "Início de capítulo": "Chapter start", "Remover": "Remove",
    "ou arraste para reordenar": "or drag to reorder", "Novas importações somam páginas a esta HQ.": "New imports add pages to this comic.",
    "Título do capítulo que começa nesta página:": "Title of the chapter starting on this page:",
    "Adicione imagens primeiro.": "Add images first.",
    "{n} página": "{n} page", "{n} páginas": "{n} pages", "{n} fonte": "{n} source", "{n} fontes": "{n} sources",
    "{pages} nesta HQ ({sources}).": "{pages} in this comic ({sources}).",
    # File dialogs and tasks
    "Imagens (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)": "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)",
    "Escolher PDF": "Choose PDF", "Escolher PDF de HQ": "Choose comic PDF", "Salvar EPUB": "Save EPUB",
    "Escolher imagens": "Choose images", "Escolher pasta de imagens": "Choose image folder",
    "Analisando PDF...": "Analyzing PDF...", "Gerando EPUB...": "Creating EPUB...",
    "Gerando EPUB de HQ...": "Creating comic EPUB...", "Baixando imagens da página...": "Downloading page images...",
    "Convertendo páginas do PDF...": "Converting PDF pages...", "Lendo pasta...": "Reading folder...",
    "Cancelando...": "Cancelling...", "Tarefa cancelada.": "Task cancelled.",
    "Falha: {message}": "Error: {message}",
    "EPUB salvo em {path}": "EPUB saved to {path}",
    "A pasta deste EPUB não existe mais.": "The folder for this EPUB no longer exists.",
    "Baixando {done}/{total} — {detail}": "Downloading {done}/{total} — {detail}",
    "Nenhuma imagem foi encontrada nessa pasta.": "No images were found in that folder.",
    "Nenhuma imagem de página foi encontrada. Tente salvar as imagens e usar 'Adicionar pasta'.": "No page images were found. Save the images and use 'Add folder'.",
    # URL import
    "Importar": "Import", "Importar imagens": "Import images",
    "Cole um ou vários links (um por linha) de imagens ou páginas públicas:": "Paste one or more links (one per line) of public images or pages:",
    "Nenhum link válido para importar.": "No valid link to import.",
    "{n} link pronto": "{n} link ready", "{n} links prontos": "{n} links ready",
    "{n} linha inválida ignorada": "{n} invalid line ignored", "{n} linhas inválidas ignoradas": "{n} invalid lines ignored",
    "{n} link": "{n} link", "{n} links": "{n} links",
    "{pages} de {links}": "{pages} of {links}", "{n} ignoradas": "{n} skipped",
    "link {position} falhou: {reason}": "link {position} failed: {reason}", "limitado a 300": "limited to 300",
    # Drag and drop
    "Solte para importar": "Drop to import",
    "Formato não suportado. Solte um PDF, imagens ou uma pasta.": "Unsupported format. Drop a PDF, images or a folder.",
    "Só o primeiro PDF foi usado.": "Only the first PDF was used.",
    "Alguns itens foram ignorados.": "Some items were ignored.",
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
    "A capa personalizada não foi encontrada. Escolha outra imagem ou remova a seleção.": "The custom cover was not found. Choose another image or remove the selection.",
    "Uma página da HQ não foi encontrada no disco. Adicione a imagem novamente antes de exportar.": "One comic page was not found on disk. Add the image again before exporting.",
    "O PDF de origem não foi encontrado. Analise o arquivo novamente antes de exportar.": "The source PDF was not found. Analyze the file again before exporting.",
    "Informe um endereço HTTP ou HTTPS.": "Enter an HTTP or HTTPS address.",
    "O endereço não contém uma página HTML ou imagem.": "The address does not contain an HTML page or image.",
    "A página HTML é grande demais para importar com segurança.": "The HTML page is too large to import safely.",
    "Nenhuma imagem foi encontrada na página.": "No images were found on the page.",
    "Nenhuma imagem pôde ser baixada desta página.": "No image from this page could be downloaded.",
    "Não foi possível acessar o endereço.": "The address could not be reached.",
    "O endereço demorou demais para responder.": "The address took too long to respond.",
    "Nenhuma imagem pôde ser importada dos endereços informados.": "No image could be imported from the given addresses.",
    "Baixando imagem...": "Downloading image...",
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
        (r"^A estrutura do PDF está inconsistente: a página (\d+) não possui uma função definida\.$", r"The PDF structure is inconsistent: page \1 has no role assigned."),
        (r"^Não foi possível gravar o EPUB em (.*?)\. Verifique o espaço em disco e a permissão da pasta\.$", r"Could not write the EPUB to \1. Check disk space and folder permissions."),
        (r"^Não foi possível gravar o EPUB em (.*)$", r"Could not write the EPUB to \1"),
        (r"^Falha ao acessar o endereço \(HTTP (\d+)\)\.$", r"The address returned HTTP \1."),
        (r"^Imagem (\d+) de (\d+)$", r"Image \1 of \2"),
    ):
        if re.match(pattern, message):
            return re.sub(pattern, replacement, message)
    return message
