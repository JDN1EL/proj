# PES 2018 Xbox 360 Editor & Elenco Sync Engine v0.5

## Principais Novidades & Recursos Implementados:

1. **Redundância de APIs (Failover em 3 Níveis)**:
   - Consulta sequencial de 3 APIs de futebol REST.
   - Pula automaticamente para a próxima se alguma falhar.
2. **Modo Offline & Cache Local**:
   - Salva automaticamente as respostas em `cache_elencos_pes2018.json`.
   - Se estiver sem conexão, atualiza a partir do último banco baixado.
   - Exibe mensagem explicativa caso não haja cache disponível.
3. **Gerenciamento de Alterações Manuais**:
   - Lembra de transferências manuais feitas pelo usuário em `alteracoes_manuais.json`.
   - Pergunta se deseja sobrescrever edições manuais ao executar "Atualizar Todos os Elencos".
4. **Exportação de Arquivos**:
   - Suporte completo a salvamento nos formatos `EDIT00000000` e `data.bin`.
5. **UI Responsiva & Logs**:
   - Interface redesenhada com Tkinter Grid weights para ajuste automático ao redimensionar a janela.
   - Logs gravados em tempo real no arquivo `pes2018_editor.log`.

## Como Gerar o Arquivo Executável (.exe) no Windows:
1. Clique duas vezes no arquivo **`GERAR_EXE_WINDOWS.bat`**.
2. O script vai baixar as dependências e compilar a pasta pronta com o `.exe` dentro do diretório `dist/`.
