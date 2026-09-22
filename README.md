# Conversor EPUB

Aplicativo local para criar EPUBs a partir de livros em PDF ou páginas de mangá/HQ. Os arquivos são processados no computador.

## Executar

Requer Python 3.10 ou superior. No Linux, Windows ou macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m conversor
```

No Windows, use `.venv\Scripts\python.exe` no lugar de `.venv/bin/python`.

## Livro em PDF

1. Importe o PDF.
2. Revise os blocos identificados. Você pode mudar o tipo de um bloco, corrigir o texto, alterar a classificação da página e reordenar blocos dentro da mesma página.
3. Escolha a página usada como capa e confira a prévia.
4. Exporte o EPUB de texto fluido. O leitor de EPUB controla o tamanho da fonte.

A análise detecta páginas com pouco texto, títulos por tamanho e padrões, possíveis capas e páginas iniciais, imagens e cabeçalhos/rodapés repetidos. Páginas escaneadas passam por OCR em português e inglês quando a biblioteca Tesseract está disponível no sistema. Os modelos de idioma estão incluídos em `resources/tessdata`. É uma primeira heurística, sujeita a correção na interface. Tabelas complexas, notas com referências cruzadas e formatação tipográfica detalhada ainda precisam de tratamento próprio.

## Mangá / HQ

1. Adicione imagens ou uma pasta. Também é possível importar imagens visíveis de uma URL pública; confira se você tem autorização para baixar e reutilizar o conteúdo.
2. Revise a ordem, marque a capa e os inícios de capítulo.
3. Escolha a direção de leitura e exporte um EPUB de layout fixo.

Sites que montam as imagens com JavaScript, exigem login ou oferecem apenas miniaturas podem precisar de arquivos baixados manualmente. O importador não contorna essas restrições.

## Desenvolvimento

O motor de análise está em `conversor/pdf_analysis.py`, a exportação em `conversor/epub_export.py` e a interface em `conversor/gui.py`. Para rodar os testes:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

O próximo passo de qualidade é testar com PDFs reais: livro digital, PDF escaneado, duas colunas e livro ilustrado. A detecção automática só pode ser calibrada com exemplos representativos.

Os modelos `por.traineddata` e `eng.traineddata` vêm do [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast), sob Apache-2.0. A licença está em `resources/tessdata/LICENSE`.
