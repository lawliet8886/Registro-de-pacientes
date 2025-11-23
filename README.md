# Registro de Pacientes

Aplicação PyQt5 para acompanhar entrada, permanência e saída dos pacientes.

## Uso rápido
1. Instale as dependências: `pip install -r requirements.txt` (PyQt5 e pandas).
2. Execute a aplicação: `python registro_pac.py`.
3. O backup automático utiliza o banco `patients.db` na raiz do projeto.

## Estrutura
- `main.py`: ponto principal da lógica da interface.
- `dialogs.py`: diálogos auxiliares (busca, horário, encaminhamento).
- `widgets.py`: widgets personalizados usados nas telas.
- `backup.py`: utilitários de backup e configuração.
- `registro_pac.py`: inicializador simples da aplicação.
