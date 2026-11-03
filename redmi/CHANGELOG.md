# Histórico de versões — PES2018 X360 Editor

## v0.4 Beta — nova lógica de elenco
- Preservados os recursos da v0.4.
- Ordenação alfabética inicial de equipes, elencos e banco, ignorando acentos e caixa.
- Abertura de `data.bin` e de pacote `EDIT00000000` CON/STFS (extração e verificação de hashes em memória).
- Transferir: remove da origem, compacta e adiciona ao destino; preserva o número da camisa se o novo número ficar vazio.
- Adicionar: inclui jogador do banco global mantendo associações existentes.
- Convocar: fluxo separado de inclusão sem remover o clube original.
- Salvamento de EDIT como `data_EDITADO.bin` para substituição manual pelo Horizon; não altera o pacote original.
- `GERAR_EXE_WINDOWS.bat` para gerar o executável no Windows.

## v0.4 — usabilidade, ordenação e histórico
- Barra inferior com instruções contextuais.
- Ordenação multicoluna acumulativa e persistente.
- Ícones compactos para salvar, desfazer e refazer.
- Histórico de até 100 operações e indicador de alterações pendentes.
- Backup automático e proteção do arquivo original.

## v0.3 — compatibilidade e dados de equipe
- Contagem de equipes/elencos lida do cabeçalho (508/510 testados).
- Recuperação com opção “Carregar mesmo assim” e modo somente leitura em caso de risco.
- Pré-visualização e cópia de formações/táticas.

## v0.2 — editor de dados e elencos
- Consulta e edição de jogadores, atributos, habilidades e estilos COM.
- Edição de equipes, elencos e camisas.
- Exportação CSV e cópia de elencos/modelos.
