# Diagnóstico e soluções aplicadas

Este documento reúne os problemas observados durante a homologação e o que foi alterado para torná-los reproduzíveis e tratáveis. Uma parada segura indica que a etapa não foi confirmada; ela não significa que o clique ou o download ocorreram.

## Python ausente no computador

**Sintoma:** `py` informou que não havia runtime Python 3.12 e a execução terminou antes da automação.

**Causa:** o lançador Python estava instalado, mas não havia um interpretador compatível selecionável. O comando `py` não instala sozinho uma versão que não está presente.

**Tratamento:** o detector procura instalações reais de Python 3.12 ou superior e verifica a versão executada, sem confiar apenas no atalho da Microsoft Store. O instalador agora tenta compilar o EXE somente quando ele está ausente. A distribuição com EXE pré-compilado não precisa do Python na máquina de destino.

## Certificado solicitado em cada domínio

**Sintoma:** Edge solicitava certificado para `online.sefaz.am.gov.br` e também para `sistemas.sefaz.am.gov.br`.

**Causa:** a SEFAZ usa mais de um domínio durante autenticação e consulta. A seleção automática configurada para o primeiro host não cobria o segundo.

**Tratamento:** `configurar_certificado_edge.ps1` grava políticas de seleção automática para os dois hosts, associando titular e emissor do certificado da conta. A importação do certificado é condicional: reutiliza o certificado válido que já estiver instalado; na distribuição protegida, importa o PFX apenas se estiver ausente e pede a senha durante a instalação.

## Item Download XML visível, mas sem clique confirmado

**Sintoma:** o menu NF-e mostrava “NF-e - Download de Arquivos XML”, mas a rotina parava em “Marcadores HTML não apareceram na captura de tela”.

**Causa observada:** o portal legado exibe o alvo no DOM sem expô-lo sempre como controle acessível único. Nas execuções com janela parcialmente fora da tela, DevTools/modo responsivo ou coordenadas de captura divergentes, o elemento HTML e a imagem da janela não podiam ser relacionados com segurança.

**Tratamento:** a rotina primeiro tenta identificar um único controle físico pelo texto exato. Se o Edge não expuser o item como controle, compara a referência visual do item inteiro com a captura local e só então faz o clique físico. As janelas pessoais do Edge não são usadas. Se o alvo não for localizado de forma única e dentro da janela, nenhum clique é feito; isso evita selecionar outro item por engano.

**Condição para o teste:** deixe a janela do Edge inteira visível em uma tela conectada e sem DevTools ou modo responsivo abertos. A captura precisa permitir localizar a referência do item dentro da janela controlada.

## Aviso de sessão antes do painel DT-e

**Sintoma:** a página mostrava um aviso de sessão, mas a inscrição e o painel DT-e apareciam depois da autenticação.

**Tratamento:** a espera não depende apenas do texto do aviso. Ela aguarda controles oficiais do painel e prossegue quando a tela autenticada é confirmada. O portal ainda pode abrir a caixa nativa de seleção de certificado; a política automática reduz essa interação quando o certificado instalado corresponde à regra configurada.

## Recuperação de horário e internet indisponível

**Sintoma:** a tarefa poderia perder o horário se o computador estivesse desligado ou sem conexão.

**Tratamento:** a tarefa tem gatilho diário, gatilho no logon, `StartWhenAvailable` e limite de execução de até sete dias. O processo aguarda a conexão dentro do limite configurado. O computador deve estar ligado e a usuária conectada; a tarefa não pode ligar o computador nem acessar o certificado antes do logon.

## Execução operacional registrada

Em 28/10/2026, a tarefa agendada foi executada às 20:42 no computador de homologação. O log registrou autenticação automática, consulta do período configurado, download e validação do ZIP; a tarefa terminou com código `0`. Esse registro comprova aquela execução específica, não substitui a confirmação na máquina de destino.

## Como coletar evidências de uma nova falha

Guarde apenas:

- as últimas 30 a 50 linhas de `%LOCALAPPDATA%\RPA_SEFAZ\logs`;
- uma captura da janela inteira do Edge, sem DevTools;
- o horário aproximado e se a conexão estava ativa.

Antes de compartilhar, oculte CNPJ, inscrição estadual, dados de notas, nomes e identificadores do certificado.
