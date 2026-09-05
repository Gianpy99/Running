// init.groovy.d script: creates the Jenkins job "ai-running-coach" and starts the
// first build. Idempotent + self-removing (not re-run on later Jenkins restarts).
// Mirrors FamilyPortal/scripts/pi/mygarage-setup.groovy.
//
// Deploy: docker cp this file into the Jenkins container's init.groovy.d, then
// restart Jenkins:
//   docker cp deploy/running-coach-setup.groovy ci_cd_validation_jenkins_1:/var/jenkins_home/init.groovy.d/running-coach-setup.groovy
//   docker restart ci_cd_validation_jenkins_1
import jenkins.model.*

def jobName = 'ai-running-coach'
def xml = '''<?xml version='1.1' encoding='UTF-8'?>
<flow-definition plugin="workflow-job">
  <description>AI Running Coach - build &amp; deploy container (FastAPI/uvicorn on 8094)</description>
  <keepDependencies>false</keepDependencies>
  <properties/>
  <definition class="org.jenkinsci.plugins.workflow.cps.CpsScmFlowDefinition" plugin="workflow-cps">
    <scm class="hudson.plugins.git.GitSCM" plugin="git">
      <configVersion>2</configVersion>
      <userRemoteConfigs>
        <hudson.plugins.git.UserRemoteConfig>
          <url>https://github.com/Gianpy99/Running.git</url>
          <credentialsId>github-gianpy99</credentialsId>
        </hudson.plugins.git.UserRemoteConfig>
      </userRemoteConfigs>
      <branches>
        <hudson.plugins.git.BranchSpec>
          <name>*/main</name>
        </hudson.plugins.git.BranchSpec>
      </branches>
      <doGenerateSubmoduleConfigurations>false</doGenerateSubmoduleConfigurations>
      <submoduleCfg class="empty-list"/>
      <extensions/>
    </scm>
    <scriptPath>Jenkinsfile</scriptPath>
    <lightweight>true</lightweight>
  </definition>
  <triggers/>
  <disabled>false</disabled>
</flow-definition>'''

def jenkins = Jenkins.instance
try {
    if (jenkins.getItem(jobName) == null) {
        def is = new ByteArrayInputStream(xml.getBytes('UTF-8'))
        jenkins.createProjectFromXML(jobName, is)
        println "[running-coach-setup] Job '${jobName}' creato."
    } else {
        println "[running-coach-setup] Job '${jobName}' gia' esistente."
    }
    def job = jenkins.getItem(jobName)
    if (job != null && job.getBuilds().isEmpty()) {
        job.scheduleBuild2(0)
        println "[running-coach-setup] Prima build avviata."
    }
} catch (Exception e) {
    println "[running-coach-setup] ERRORE: ${e}"
}
// auto-removal so it does not re-run on future restarts
try { new File('/var/jenkins_home/init.groovy.d/running-coach-setup.groovy').delete() } catch (ignored) {}
