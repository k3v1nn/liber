# Liber

Aplicativo local para criar EPUBs a partir de livros em PDF ou páginas de mangá/HQ. Os arquivos são processados no computador.

*Liber* é “livro” em latim, e também “livre”.

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
   Você também pode escolher uma imagem de capa própria sem alterar as páginas do livro.
4. Exporte o EPUB de texto fluido. O leitor de EPUB controla o tamanho da fonte.

O sumário do EPUB usa os títulos dos blocos classificados como **Capítulo**, inclusive quando o primeiro capítulo inicia o conteúdo do livro. Textos introdutórios anteriores ao primeiro capítulo continuam em uma seção separada.

A análise detecta páginas com pouco texto, títulos por tamanho e padrões, possíveis capas e páginas iniciais, imagens e cabeçalhos/rodapés repetidos. Páginas escaneadas passam por OCR em português e inglês quando a biblioteca Tesseract está disponível no sistema. Os modelos de idioma estão incluídos em `resources/tessdata`. É uma primeira heurística, sujeita a correção na interface. Tabelas complexas, notas com referências cruzadas e formatação tipográfica detalhada ainda precisam de tratamento próprio.

## Mangá / HQ

1. Adicione imagens, uma pasta ou um PDF de HQ. Cada página do PDF entra na lista como imagem, na ordem original. Também é possível importar imagens visíveis de uma URL pública; confira se você tem autorização para baixar e reutilizar o conteúdo.
2. Revise a ordem, marque a capa e os inícios de capítulo.
   Uma imagem de capa própria pode ser adicionada separadamente das páginas.
3. Escolha a direção de leitura e exporte um EPUB de layout fixo.

Ao importar uma galeria por URL, os caminhos relativos das imagens são resolvidos a partir do endereço final da página, inclusive após redirecionamentos HTTP.

Sites que montam as imagens com JavaScript, exigem login ou oferecem apenas miniaturas podem precisar de arquivos baixados manualmente. O importador não contorna essas restrições.

O PDF importado nesta aba é convertido em páginas ilustradas para EPUB de layout fixo. Para livros cujo texto deve se adaptar à tela, use a aba **Livro em PDF**.

Páginas ilustradas e imagens de capa respeitam a orientação EXIF (rotação e espelhamento) na prévia e no EPUB. A importação por URL aplica essa orientação ao PNG baixado; a exportação não a aplica novamente. Os arquivos originais não são modificados.

## Interface

O aplicativo abre numa tela escura com os dois caminhos, **Livro em PDF** e **Mangá / HQ**, e uma estante curva com os últimos EPUBs gerados. Clicar num livro da estante abre a pasta do arquivo. Antes do primeiro EPUB, a estante mostra clássicos em domínio público. Também é possível arrastar um PDF, imagens ou uma pasta para qualquer ponto da janela.

A área de trabalho usa fundo de papel e três colunas:

- **Livro** ou **HQ**: título, autor, idioma e capa. Na HQ, o interruptor define a leitura da direita para a esquerda.
- **Estrutura** (PDF): os blocos aparecem como um sumário, com capítulos em destaque, até duas linhas de texto por parágrafo e um selo para notas, imagens, legendas e blocos ignorados. Ao selecionar um bloco, o editor abre logo abaixo dele, com o tipo do bloco, o tipo da página, o texto, **Aplicar correção** e as setas para reordenar. Os filtros mostram só capítulos, notas, imagens ou blocos ignorados.
- **Páginas** (HQ): miniaturas que podem ser arrastadas para mudar a ordem. A ★ marca a capa e a fita vermelha marca o início de capítulo.
- **Prévia**: a página EPUB ou a página original do PDF.

As quatro formas de adicionar páginas de HQ (**Imagens**, **Pasta**, **PDF de HQ** e **URL pública**) ficam visíveis na barra superior e na tela vazia. A fita vermelha sob a barra superior indica uma tarefa em andamento, e o rodapé mostra a última mensagem. Em janelas mais estreitas, os dados do livro passam para uma faixa no topo e, abaixo de 860 px, as colunas ficam empilhadas. O seletor **PT · EN** alterna o idioma.

As fontes Fraunces e Inter vêm em `assets/fonts`, sob a SIL Open Font License 1.1 (`Fraunces-OFL.txt` e `Inter-OFL.txt`).

## Executáveis

Baixe o ZIP do seu sistema na seção **Releases** do repositório. O código inclui um [workflow de build](.github/workflows/build.yml) para Linux x64, Windows x64 e macOS Intel/Apple Silicon. O repositório privado só permite o download a pessoas com acesso; para outros testadores, envie o ZIP diretamente.

Para gerar no computador atual, instale as dependências e o PyInstaller no ambiente virtual e execute:

```bash
.venv/bin/python -m pip install 'pyinstaller>=6.15,<7'
.venv/bin/python build.py
```

No Windows, use `.venv\Scripts\python.exe`. O pacote fica em `release/` e contém o aplicativo, a licença e `codigo-fonte.zip`. Descompacte o ZIP antes de executar. O build precisa rodar em cada sistema operacional; o PyInstaller não gera executáveis de outros sistemas a partir do Linux. Os pacotes ainda não são assinados digitalmente. O executável Linux criado em distribuições recentes pode depender de uma versão de glibc igualmente recente.

## Desenvolvimento

O motor de análise está em `conversor/pdf_analysis.py` e a exportação em `conversor/epub_export.py`. A interface fica em `conversor/gui.py` (comportamento), `conversor/ui_layout.py` (montagem das telas), `conversor/widgets.py` (componentes desenhados, como a estante e o sumário) e `conversor/appearance.py` (cores, fontes, ícones, logo e estilo). Para rodar os testes:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Os testes de imagens da interface usam Qt em modo `offscreen`, sem precisar abrir uma janela nem alterar as preferências de idioma do usuário.

O próximo passo de qualidade é testar com PDFs reais: livro digital, PDF escaneado, duas colunas e livro ilustrado. A detecção automática só pode ser calibrada com exemplos representativos.

Os modelos `por.traineddata` e `eng.traineddata` vêm do [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast), sob Apache-2.0. A licença está em `resources/tessdata/LICENSE`.

## Licença

O código deste aplicativo é distribuído sob a [GNU Affero General Public License, versão 3](LICENSE) (`AGPL-3.0-only`). Ela permite usar, estudar, modificar e redistribuir o aplicativo, inclusive comercialmente, desde que seus termos sejam cumpridos. Versões modificadas distribuídas e determinadas formas de disponibilização pela rede exigem acesso ao código-fonte correspondente.

Os modelos de OCR mantêm a licença Apache-2.0 indicada acima, e as fontes, a SIL Open Font License 1.1. As demais bibliotecas instaladas por `requirements.txt` mantêm suas próprias licenças.

Os EPUBs criados pelo aplicativo não recebem automaticamente a licença do código. Os direitos sobre textos, imagens e outros materiais de origem continuam sujeitos às licenças e autorizações desses materiais.
