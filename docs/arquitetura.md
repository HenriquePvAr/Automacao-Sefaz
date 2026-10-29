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

## Modelo orientado a objetos

O núcleo concentra a automação em uma classe de infraestrutura e funções de domínio pequenas. Essa divisão dá um ponto claro para substituir ou depurar a interação com o Edge sem misturar cada passo de negócio com o agendamento.

```mermaid
classDiagram
    class NavegadorNormal {
      +start()
      +navigate(url)
      +focus()
      +click_sefaz_banner()
      +click_xml_with_calibrated_mouse()
      +field(names, label, value)
      +close_owned_window_if_safe()
    }
    class ErroSeguro {
      +motivo: str
    }
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

### Princípios de projeto aplicados

- **Encapsulamento:** `NavegadorNormal` mantém a janela criada pela automação e suas operações, sem manipular as janelas pessoais do usuário.
- **Responsabilidade única:** funções separadas calculam períodos, validam o ZIP, registram o estado, identificam o painel e operam a consulta.
- **Abstração:** o fluxo de negócio chama métodos como `field` e `click_sefaz_banner`, sem repetir detalhes de teclado, DPI e UI Automation.
- **Falha segura:** `ErroSeguro` interrompe a rotina quando o alvo não é único, a página não corresponde ao domínio/caminho esperado ou o clique não pode ser confirmado.
- **Injeção de configuração:** URL, inscrição, horários e limites são lidos de `config.json`, em vez de ficarem fixos no fluxo.

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
