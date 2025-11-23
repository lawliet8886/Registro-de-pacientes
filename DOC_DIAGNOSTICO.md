# Diagnóstico e Arquitetura

## Visão geral
A aplicação é um cliente desktop em PyQt5 responsável por registrar entradas, saídas, refeições e demandas de pacientes em um banco SQLite local (`patients.db`). A tela principal é montada pela classe `Main` (herda `QMainWindow`), que inicializa o banco via `init_db()` e organiza abas de acompanhamento, consolidados e ações rápidas para importação/exportação e correções.

## Componentes principais
- **Persistência**: `init_db()` cria/migra tabelas `records`, `meal_log` e `demand_log`, garantindo compatibilidade com bancos antigos. Operações de leitura/escrita usam `sqlite3` direto, mantendo o banco na raiz do projeto.
- **Interface**: `Main` constrói o layout com filtros por data, campos de paciente, checkboxes de refeições e múltiplas abas de tabelas. Botões acionam ações críticas como registrar, marcar saída, editar refeições, importar Excel e gerar backups.
- **Backup**: a função `backup_now()` copia `patients.db` para um diretório configurável (por padrão em `G:\Meu Drive\backup_recepção`), com feedback visual. Chamadas automáticas ocorrem a cada 2 horas via `QTimer` e ao fechar a janela.

## Áreas críticas a observar
- **Disponibilidade de backup**: se o caminho padrão do Google Drive não estiver acessível, a aplicação solicita nova pasta. Falhas de escrita podem impedir backups automáticos; validar permissões periodicamente.
- **Integridade do banco**: como o SQLite fica na raiz do aplicativo, é importante evitar múltiplas instâncias gravando simultaneamente e sempre manter cópias recentes antes de atualizações.
- **Migrações silenciosas**: o app atualiza colunas ausentes e corrige dados antigos automaticamente. Embora conveniente, mudanças de esquema devem ser acompanhadas de backups prévios e testes manuais.
- **Dependências de interface**: a execução exige ambiente gráfico compatível com PyQt5. Em servidores ou WSL sem suporte a GUI, será necessário configurar um servidor X ou usar o aplicativo em máquinas com desktop.

## Sugestões de próximos passos
- Adicionar suíte de testes (por exemplo, `pytest`) cobrindo rotinas de banco e funções de backup.
- Automatizar a geração de builds empacotados (PyInstaller) com configuração padrão de backup.
- Documentar fluxos de importação/exportação (planilhas) e limites esperados para volume de dados.
