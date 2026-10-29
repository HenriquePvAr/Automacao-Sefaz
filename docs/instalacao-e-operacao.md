# Instalação e operação

## Pré-requisitos

- Windows 10 ou 11, conta da usuário que fará as consultas e conexão com a internet.
- Microsoft Edge instalado.
- Certificado digital válido, com chave privada, disponível no armazenamento **Pessoal** da mesma conta Windows que executará a automação.
- Pacote de implantação com EXE, ou Python 3.12+ para compilar o código-fonte durante a instalação.

O computador precisa estar ligado e a usuário precisa entrar no Windows. A tarefa usa o certificado e o perfil dessa sessão; não executa antes do logon. Se o horário diário for perdido, o gatilho de logon inicia uma nova tentativa. Se faltar internet, o processo aguarda dentro do limite definido.

## Instalar na máquina de destino

1. Baixe o pacote de implantação preparado ou clone/extraia este repositório.
2. Mantenha a pasta `aplicativo` em um caminho permanente; não execute de dentro do visualizador de ZIP nem de uma pasta temporária.
3. Entre na conta Windows que fará as consultas e execute `aplicativo\instalar.bat`.
4. Se solicitado, informe a inscrição estadual da matriz. A configuração ativa é gravada em `%LOCALAPPDATA%\RPA_SEFAZ\config.json` dessa conta.
5. Se o certificado válido já estiver instalado, ele é reaproveitado. Um pacote protegido pode incluir um PFX: se o certificado correspondente estiver ausente, o instalador pede a senha durante a importação e não a grava.
6. O instalador configura o Edge para selecionar o certificado nos dois domínios da SEFAZ-AM, cria `Área de Trabalho\Notas sefaz`, copia `Automacao Notas Sefaz.exe` para a Área de Trabalho e registra a tarefa diária.
7. Feche e abra o Edge para recarregar a política de seleção automática. Use o atalho da Área de Trabalho para uma consulta manual e confirme a criação do ZIP.

Quando o EXE não estiver presente, `instalar.bat` chama `gerar_executavel.bat`. A compilação usa um ambiente isolado em `%LOCALAPPDATA%\RPA_SEFAZ\venv`, instala `requirements.txt` e grava o executável na pasta `aplicativo`. A máquina precisa ter Python 3.12+ e acesso à internet para essa etapa. O pacote de implantação com EXE já pronto dispensa Python na máquina destino.

## Execução manual e agendada

| Ação | Como iniciar | O que aparece |
|---|---|---|
| Consulta manual | Dois cliques em `Automacao Notas Sefaz.exe` na Área de Trabalho | Tela pequena de progresso; Edge permanece oculto. |
| Consulta agendada | Tarefa `RPA_SEFAZ_Download_XML` | Edge e console ocultos; detalhes no log. |
| Reagendar | Edite `hora_diaria` e execute `aplicativo\agendar_tarefa.bat` | A tarefa é atualizada para o horário informado. |
| Recompilar | Execute `aplicativo\gerar_executavel.bat` | Gera/atualiza o EXE dentro de `aplicativo`. |

O valor de `hora_diaria` usa 24 horas e formato `HH:mm`, por exemplo `20:42`. A tarefa diária também tem um gatilho de logon e a configuração `StartWhenAvailable` para recuperar o horário quando a máquina estava desligada. Isso não liga o computador desligado.

## Pastas e retenção

```text
Área de Trabalho\
├── Automacao Notas Sefaz.exe
└── Notas sefaz\
    └── nota 28-10-2026\
        └── ZIP original baixado

%LOCALAPPDATA%\RPA_SEFAZ\
├── config.json
├── estado.json
├── logs\
└── venv\                   # Presente se o EXE foi compilado nessa máquina
```

A automação mantém o ZIP original e organiza cada execução em uma pasta diária. O estado permite reconhecer o último período concluído; o log registra etapa, horários e falhas para diagnóstico.

## Alterar horário ou parâmetros

Edite `%LOCALAPPDATA%\RPA_SEFAZ\config.json` na conta que executará o robô. Campos operacionais:

| Campo | Uso |
|---|---|
| `hora_diaria` | Horário diário, em `HH:mm`. Depois de alterar, execute `aplicativo\agendar_tarefa.bat`. |
| `empresa_inscricao_estadual` | Inscrição estadual da matriz usada na seleção do contribuinte. |
| `aguardar_internet_horas` | Limite de espera por reconexão. |
| `aguardar_certificado_segundos` | Tempo máximo para a etapa de autenticação. |
| `aguardar_painel_dte_segundos` | Limite para confirmar o painel DT-e. |
| `aguardar_consulta_xml_segundos` | Limite para confirmar a página da consulta. |
| `aguardar_download_segundos` | Limite para terminar o download. |

Para evitar trocar o horário e esquecer a tarefa antiga, execute sempre `agendar_tarefa.bat` depois de salvar o novo valor.

## Diagnóstico operacional

1. Abra o log mais recente em `%LOCALAPPDATA%\RPA_SEFAZ\logs`.
2. Confira se o Edge está instalado e se o certificado aparece como válido na conta Windows atual.
3. Se o seletor de certificado voltar a aparecer, encerre todas as janelas do Edge, confirme as políticas e abra o navegador novamente.
4. Se a consulta parar no item de download, confira se a janela está inteira dentro de uma tela conectada, sem DevTools/modo responsivo. A automação não clica quando não consegue confirmar o item visualmente.
5. Se o ZIP não aparecer, consulte o log e a tarefa `RPA_SEFAZ_Download_XML` no Agendador de Tarefas.

Veja [diagnóstico e soluções](diagnostico-e-solucao.md) para os erros já encontrados.
