# Automação de Notas SEFAZ-AM

Aplicativo Windows para consultar e baixar XML de documentos fiscais recebidos no Domicílio Tributário Eletrônico (DT-e) da SEFAZ-AM. A consulta pode ser iniciada manualmente pela tela de progresso ou executada em segundo plano pelo Agendador de Tarefas do Windows.

> **Escopo:** a automação consulta a SEFAZ-AM e guarda o ZIP no computador. Ela não envia documentos ao Sankhya.

## O que está neste repositório

```text
.
├── aplicativo/                 # Fontes e scripts autocontidos para Windows
├── docs/
│   ├── arquitetura.md          # Componentes, classes e diagramas Mermaid
│   ├── diagnostico-e-solucao.md# Histórico técnico dos problemas resolvidos
│   ├── instalacao-e-operacao.md# Instalação, agenda e pastas de saída
│   └── evidencias/             # Evidência operacional sanitizada
└── README.md
```

Os fontes, arquivos de configuração de exemplo e scripts de instalação ficam em `aplicativo/`. O executável pode ser gerado nessa pasta durante a instalação quando Python 3.12 ou superior estiver disponível. O pacote de implantação pode levar o executável já compilado para que a máquina de destino não precise do Python.

## Instalação

1. Baixe o ZIP de código pelo botão **Code → Download ZIP** ou clone este repositório.
2. Extraia a pasta `aplicativo` para um local permanente no computador Windows.
3. Execute `aplicativo\instalar.bat` na conta Windows que fará as consultas.
4. Quando solicitado, informe a inscrição estadual da matriz. Um certificado válido com chave privada precisa estar instalado nessa conta; um pacote de implantação protegido pode instalá-lo se estiver ausente.
5. Feche e abra o Edge após a configuração do certificado e faça uma consulta pelo atalho `Automacao Notas Sefaz.exe` na Área de Trabalho.

O instalador cria a pasta `Área de Trabalho\Notas sefaz`, copia o executável para a Área de Trabalho e registra uma tarefa diária às 07:30, além de uma tentativa no próximo logon para recuperar horário perdido. O usuário precisa estar conectado ao Windows para o certificado e o perfil da conta estarem disponíveis.

> Se a instalação for feita a partir do código-fonte e não houver um EXE na pasta, o instalador tenta gerar o executável. Para essa compilação, é necessário Python 3.12+; sem Python, use o pacote de implantação com o EXE já compilado.

## Resultado

```text
Área de Trabalho\
└── Notas sefaz\
    └── nota DD-MM-AAAA\
        └── arquivo ZIP original baixado da SEFAZ-AM
```

Os arquivos originais ZIP são preservados. Logs e estado da execução ficam em `%LOCALAPPDATA%\RPA_SEFAZ\`.

## Arquitetura e manutenção

- [Arquitetura e modelo orientado a objetos](docs/arquitetura.md)
- [Instalação, agendamento e operação](docs/instalacao-e-operacao.md)
- [Problemas encontrados e soluções aplicadas](docs/diagnostico-e-solucao.md)
- [Evidência de execução](docs/evidencias/execucao-agendada-2026-10-28.md)

Para alterar o horário, edite `%LOCALAPPDATA%\RPA_SEFAZ\config.json` (`hora_diaria`, formato `HH:mm`) e execute `aplicativo\agendar_tarefa.bat` novamente. Para recompilar somente o executável, execute `aplicativo\gerar_executavel.bat`.

## Tecnologia

Python 3.12+, Playwright, PyAutoGUI, Pillow, pywinauto, pywin32, psutil, PyInstaller, PowerShell e Agendador de Tarefas do Windows. A compilação gera um executável Windows de 64 bits.
