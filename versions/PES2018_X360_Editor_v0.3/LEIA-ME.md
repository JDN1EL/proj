# PES 2018 Xbox 360 — Editor v0.3

## O que mudou nesta versão

- Corrigido o erro de contagem fixa: arquivos PES 2018 com 508, 509 ou 510 equipes/elencos são lidos conforme os números do cabeçalho, desde que as tabelas caibam no layout conhecido.
- Quando houver estrutura inesperada, o aplicativo oferece **Carregar mesmo assim** ou **Cancelar**. O modo de recuperação abre em **somente leitura** quando encontra referências quebradas, contagens diferentes, registros ausentes ou outras inconsistências.
- Vínculo entre equipe, elenco e tática é feito pelo ID da equipe, e não apenas pela posição da tabela.
- Nova aba **Formações e táticas**: visualiza os 3 planos e as 9 formações registradas por equipe.
- Ações para copiar apenas as configurações de formação/tática de outra equipe ou copiar elenco + configurações. A segunda opção copia também os jogadores e números de camisa.
- O banco de jogadores permite selecionar e editar atributos de qualquer jogador, mesmo que ele não esteja no elenco selecionado. Atributos pertencem ao cadastro global do jogador; uma alteração aparece em todas as equipes que usam aquele ID.
- Cabeçalhos das tabelas agora ordenam os valores corretamente: camisa e IDs numericamente; nomes alfabeticamente.
- A janela inicia maximizada no Windows, respeitando a área de trabalho acima da barra de tarefas.
- Mantida a proteção: o arquivo original não é sobrescrito; o salvamento é feito em uma cópia com validação e backup do destino quando já existe.

## Compatibilidade

Esta versão foi validada com dois `data.bin` que usam a estrutura PES 2018 conhecida:

| Arquivo de teste | Jogadores | Equipes | Elencos | Resultado |
|---|---:|---:|---:|---|
| Base modificada recebida anteriormente | 14.936 | 510 | 510 | Compatível |
| Base original do console enviada nesta conversa | 13.290 | 508 | 508 | Compatível |

**Importante:** isso cobre variantes de `data.bin` de PES 2018 que mantêm os offsets/strides deste layout. Não significa compatibilidade automática com qualquer edição/ano da franquia PES. Arquivos com outra estrutura só podem ser abertos em recuperação se as tabelas ainda puderem ser localizadas; nesse caso a edição fica bloqueada.

## Como executar no Windows

1. Instale Python 3.10 ou superior. Na instalação oficial do Python, mantenha selecionada a opção Tcl/Tk para o Tkinter.
2. Extraia a pasta do ZIP.
3. Dê duplo clique em `INICIAR_EDITOR.bat` ou execute `python pes2018_editor_xbox360.py`.
4. Abra o `data.bin` já extraído/descriptografado.
5. Salve sempre como uma cópia diferente do arquivo original.

## Testes

Execute:

```powershell
python testar_editor_PES2018.py "C:\caminho\data.bin"
```

É possível validar várias variantes no mesmo comando:

```powershell
python testar_editor_PES2018.py "C:\teste\data-original.bin" "C:\teste\data-modificado.bin"
```

## Gerar EXE no Windows

Execute `GERAR_EXE_WINDOWS.bat`. O arquivo será criado em `dist\PES2018_X360_Editor.exe`.

## Limitações e segurança

- O editor trabalha sobre o `data.bin` já extraído/descriptografado.
- Não descriptografa nem reempacota o save/conteiner do Xbox 360, nem gera assinatura/checksum do save. Isso permanece para depois do primeiro teste real no console.
- Formações/táticas são interpretadas para visualização e podem ser copiadas de outra equipe como bloco completo. Teste a cópia apenas em arquivo de trabalho e no console com backup.
- Os 72 bytes de aparência continuam em inspeção bruta, sem edição dos subcampos não confirmados.
- Campos binários desconhecidos são preservados sempre que o editor altera um campo conhecido.
