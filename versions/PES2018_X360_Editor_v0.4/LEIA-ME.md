# PES2018 X360 Editor v0.4 Beta

Editor Python/Tkinter para `data.bin` do PES 2018 Xbox 360. Esta beta preserva os recursos da v0.4 e adiciona operações de elenco baseadas na tabela de elencos identificada nos comparativos feitos pelo próprio jogo.

## Novidades da Beta

### Abrir arquivos
- Abre `data.bin` extraído/descriptografado.
- Abre diretamente `EDIT00000000` em formato CON/STFS, verifica hashes dos blocos e extrai `data.bin` em memória.
- Ao salvar um EDIT aberto, gera uma cópia separada `data_EDITADO.bin`. O pacote original não é alterado.
- Para usar no Xbox 360, substitua o `data.bin` dentro do pacote com Horizon. Esta beta não reconstrói nem assina pacotes CON/STFS.

### Três operações de elenco
1. **Transferir jogador:** seleciona a equipe de origem entre os elencos que contêm o jogador; remove da origem, compacta o elenco e adiciona ao destino. Preserva o número de camisa por padrão (o campo Novo número permite definir outro número).
2. **Adicionar jogador:** inclui jogador do banco global no elenco selecionado, vindo de outro clube ou sem clube, sem remover suas outras associações.
3. **Convocar jogador:** inclui o jogador no elenco selecionado sem remover o vínculo original. É uma ação separada na interface para o fluxo de convocação.

Adicionar e Convocar usam a mesma representação binária confirmada até aqui: inclusão de ID e camisa no registro de elenco. A diferença é de fluxo/uso na interface; não há evidência de um campo binário separado para convocação.

### Organização alfabética
- Ordenação de nomes ignora diferenças entre maiúsculas/minúsculas e acentos (ex.: Álvarez ordena como Alvarez).
- Ordenação multicoluna continua acumulativa e mantém direção/prioridade dos critérios.

### Recursos preservados
- Pesquisa de equipes por nome, sigla ou ID.
- Banco global de jogadores e consulta/edição de dados.
- 23 atributos, 28 habilidades e 7 estilos COM identificados.
- Nomes/siglas de equipes; camisa; substituição, adição, remoção e reorganização de jogadores.
- Pré-visualização dos três planos táticos e três formações por plano; cópia de configurações e elenco conforme opção.
- CSV, histórico de 100 operações, desfazer/refazer, Ctrl+S/Ctrl+Z/Ctrl+Y, indicador de alterações, backup e proteção do original.
- Reconhecimento de layouts com até 510 equipes e abertura de recuperação em somente leitura quando houver inconsistências.
- Preservação dos bytes não interpretados.

## Instalação e execução

1. Extraia toda a pasta.
2. Para executar pelo Python, instale Python 3.10+ com Tcl/Tk e dê duplo clique em `INICIAR_EDITOR.bat`.
3. Para gerar o executável Windows, dê duplo clique em `GERAR_EXE_WINDOWS.bat`.
4. O executável será criado em `dist\PES2018_X360_Editor_Beta.exe`.

O BAT instala PyInstaller se necessário. A compilação do `.exe` deve ser feita no Windows.

## Testes

Testes binários anteriores:

```powershell
py -3 testar_editor_PES2018_v0.4.py "C:\caminho\data.bin"
```

Testes novos das operações e leitura de EDIT:

```powershell
py -3 testar_editor_PES2018_beta.py "C:\caminho\data.bin" --edit "C:\caminho\EDIT00000000"
```

Os testes da beta verificam transferência, adição mantendo associações, convocação aditiva, inclusão de jogador sem clube, atomicidade quando uma transferência é inválida e extração/verificação de `data.bin` dentro de pacote EDIT.

## Limitações e segurança

- A transferência externa altera apenas a tabela de elencos mapeada: IDs de jogador em `0x04..0x83` e números de camisa em `0x84..0xA3` de cada registro `0xA4`. Essa estrutura é consistente com o layout analisado e com os diffs observados; a validação definitiva depende do teste no console.
- A beta não altera registros individuais de jogadores, equipes ou táticas ao transferir/adicionar/convocar.
- O editor não edita nem reempacota o CON/STFS. Abrir EDIT significa verificar e extrair `data.bin`; salvar produz um `data.bin` separado para substituição manual pelo Horizon.
- Não sobrescreve o arquivo original. Sempre salve uma cópia.
- Faça teste com cópia do save e mantenha backup do EDIT original.
