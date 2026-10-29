# Arquitetura da automação

## Responsabilidade do sistema

A aplicação autentica no DT-e com o certificado instalado na conta Windows, seleciona a inscrição estadual configurada, abre a consulta de XML recebidos, informa o período, baixa o ZIP, valida o arquivo e o guarda na pasta diária. A execução manual apresenta progresso; a execução agendada usa o Edge sem janela visível.

O fluxo de negócio termina no ZIP local. O código não encaminha arquivos ao Sankhya.

## Fluxo principal

```mermaid
flowchart TD
    A[Início manual ou tarefa agendada] --> B[Carregar configuração local]
    B --> C{Internet disponível?}
    C -- Não --> D[Aguardar reconexão dentro do limite]
    D --> C
    C -- Sim --> E[Calcular período pendente]
    E --> F[Criar janela exclusiva do Edge]
    F --> G[Abrir portal oficial SEFAZ-AM]
    G --> H{Autenticação por certificado concluída?}
    H -- Não --> Z[Interromper com log]
    H -- Sim --> I[Confirmar DT-e e inscrição estadual]
    I --> J[Fechar avisos oficiais]
    J --> K[Abrir categoria NF-e]
    K --> L[Confirmar item Download XML]
    L --> M{Alvo identificado sem ambiguidade?}
    M -- Não --> Z
    M -- Sim --> N[Clicar no item e confirmar consulta]
    N --> O[Selecionar Recebidos e preencher datas]
    O --> P[Baixar ZIP]
    P --> Q{ZIP íntegro?}
    Q -- Não --> Z
    Q -- Sim --> R[Preservar ZIP em Notas sefaz\nota DD-MM-AAAA]
    R --> S[Atualizar estado e registrar conclusão]
```

## Componentes e relações

O diagrama mostra qual parte controla o navegador, qual conduz as etapas da SEFAZ e onde ficam os resultados locais. O fluxo manual exibe o progresso; o Agendador do Windows inicia a mesma consulta em segundo plano.

```mermaid
classDiagram
    class NavegadorNormal {
      +start()
      +navigate(url)
      +focus()
      +click_sefaz_banner()
      +try_click_xml_menu_physical()
      +click_xml_with_visual_template()
      +field(names, label, value)
      +close_owned_window_if_safe()
    }
    class ErroSeguro
    class Configuracao {
      +sefaz_url: str
      +empresa_inscricao_estadual: str
      +hora_diaria: str
      +aguardar_internet_horas: int
    }
    class FluxoSEFAZ {
      +wait_certificate()
      +select_company_sefaz()
      +open_sefaz_nfe_category()
      +open_sefaz_xml_download()
      +wait_for_xml_consultation()
      +download_sefaz()
    }
    class PersistenciaLocal {
      +save_state()
      +log()
      +validate_zip()
      +keep_zip_on_desktop()
    }
    class InterfaceProgresso {
      +show_manual_progress_window()
    }
    class AgendadorWindows {
      +instalar.bat
      +agendar_tarefa.ps1
      +executar_agendado.vbs
    }

    FluxoSEFAZ --> NavegadorNormal : controla a sessão isolada
    FluxoSEFAZ --> PersistenciaLocal : valida e guarda o resultado
    NavegadorNormal ..> ErroSeguro : interrompe se a tela for ambígua
    InterfaceProgresso --> FluxoSEFAZ : mostra o estado da execução manual
    AgendadorWindows --> FluxoSEFAZ : inicia em segundo plano
    FluxoSEFAZ ..> Configuracao : recebe datas e parâmetros
```

`NavegadorNormal` opera apenas a janela criada pela automação e deixa as janelas pessoais do usuário intactas. As funções de consulta confirmam cada tela antes de avançar; `ErroSeguro` encerra o fluxo quando o alvo ou a página não podem ser identificados. Os endereços, a inscrição estadual, os horários e os limites vêm da configuração local.

## Organização dos módulos

| Caminho | Papel |
|---|---|
| `aplicativo/download_sefaz_xml.py` | Orquestração, classe `NavegadorNormal`, rotinas de domínio, validação e interface manual. |
| `aplicativo/config.json` | Modelo genérico da configuração local. |
| `aplicativo/instalar.bat` e scripts PowerShell | Preparação da conta, certificado, cópia do EXE e tarefa diária. |
| `aplicativo/gerar_executavel.bat` | Instala dependências no ambiente isolado e compila o EXE. |
| `aplicativo/executar_*.bat` e `*.vbs` | Inicialização manual ou agendada sem abrir um console visível. |
| `aplicativo/acessarDTe.png` e `xml_item_template.png` | Referências visuais usadas para identificar alvos oficiais do portal. |

## Ciclo de vida e arquivos locais

```mermaid
flowchart LR
    A[instalar.bat] --> B[config.json local]
    A --> C[Certificado da conta Windows]
    A --> D[Atalho na Área de Trabalho]
    A --> E[Tarefa diária + logon]
    D --> F[Consulta manual com progresso]
    E --> G[Consulta oculta em segundo plano]
    F --> H[ZIP validado]
    G --> H
    H --> I[Área de Trabalho\Notas sefaz\nota data]
    F --> J[%LOCALAPPDATA%\RPA_SEFAZ\logs]
    G --> J
    F --> K[%LOCALAPPDATA%\RPA_SEFAZ\estado.json]
    G --> K
```
