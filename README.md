# Registro de Pacientes

Aplicação desktop em PyQt5 para registro diário de pacientes na recepção do Caps AD III Paulo da Portela. O programa mantém um banco SQLite local (`patients.db`), oferece filtros e dashboards para as demandas e refeições servidas e executa cópias de segurança automáticas.

## Requisitos
- Python 3.10 ou superior.
- [PyQt5](https://pypi.org/project/PyQt5/) para a interface gráfica.
- [pandas](https://pypi.org/project/pandas/) para importação/exportação de planilhas.

## Instalação
1. Crie e ative um ambiente virtual (opcional, mas recomendado):
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\\Scripts\\activate   # Windows
   ```
2. Instale as dependências necessárias:
   ```bash
   pip install --upgrade pip
   pip install PyQt5 pandas
   ```

## Execução da interface
1. Garanta que o diretório contenha `registro_pac.py` (o banco `patients.db` será criado ou migrado automaticamente na primeira execução).
2. Inicie a interface gráfica:
   ```bash
   python registro_pac.py
   ```
3. Utilize os filtros, abas e botões da tela principal para registrar entradas/saídas, refeições e observações. O programa mantém logs de alterações e migra dados antigos automaticamente.

## Backup da base de dados
- A aplicação mantém um botão **Backup ☁️** na tela principal. Ao acionar, o arquivo `patients.db` é copiado para uma pasta de backup configurável. Caso o Google Drive esteja em `G:\\Meu Drive`, a aplicação sugere `G:\\Meu Drive\\backup_recepção` e solicita ajuste caso não consiga gravar.
- Um backup automático roda a cada 2 horas durante o uso e outro é feito ao fechar a janela, garantindo que a última versão seja salva.
- Se preferir um backup manual, copie o arquivo `patients.db` para o local desejado com o programa fechado.

## Testes automatizados
Ainda não há suíte de testes disponível. Quando testes forem adicionados, eles devem ser executados a partir da raiz do repositório, por exemplo:
```bash
pytest
```
Certifique-se de ativar o ambiente virtual antes de rodar os testes para que as dependências estejam carregadas.

## Estrutura do repositório
- `registro_pac.py`: código principal da interface, incluindo inicialização do banco, layouts PyQt5, botões de ação (Registrar, Marcar saída, Backup, entre outros) e rotinas de backup automático/ao fechar.
- `README.md`: este guia rápido de instalação e uso.
- `DOC_DIAGNOSTICO.md`: resumo de arquitetura e pontos críticos.
