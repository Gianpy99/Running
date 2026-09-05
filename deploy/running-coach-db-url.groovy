// init.groovy.d: creates the Secret text credential 'running-coach-database-url'
// by reading it from a file (docker cp'd onto the Pi), then triggers a build of
// ai-running-coach. Idempotent + self-removing.
// Mirrors FamilyPortal/scripts/pi/mygarage-key.groovy.
//
// Usage on the Pi:
//   printf '%s' 'postgresql://running_coach:PASSWORD@192.168.1.129:1433/running_coach' \
//     | docker exec -i ci_cd_validation_jenkins_1 tee /var/jenkins_home/running-coach-dburl >/dev/null
//   docker cp deploy/running-coach-db-url.groovy ci_cd_validation_jenkins_1:/var/jenkins_home/init.groovy.d/running-coach-db-url.groovy
//   docker restart ci_cd_validation_jenkins_1
import com.cloudbees.plugins.credentials.*
import com.cloudbees.plugins.credentials.domains.Domain
import org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl
import hudson.util.Secret
import jenkins.model.Jenkins

try {
    def f = new File('/var/jenkins_home/running-coach-dburl')
    def dburl = f.text.trim()
    def store = SystemCredentialsProvider.getInstance().getStore()
    def domain = Domain.global()
    store.getCredentials(domain).findAll { it.id == 'running-coach-database-url' }.each {
        store.removeCredentials(domain, it)
    }
    def cred = new StringCredentialsImpl(CredentialsScope.GLOBAL, 'running-coach-database-url',
        'AI Running Coach shared PostgreSQL DSN', Secret.fromString(dburl))
    store.addCredentials(domain, cred)
    println '[running-coach-db-url] credenziale running-coach-database-url creata'
    f.delete()
    def job = Jenkins.instance.getItem('ai-running-coach')
    if (job != null) { job.scheduleBuild2(0); println '[running-coach-db-url] build avviata' }
} catch (e) {
    println "[running-coach-db-url] ERRORE: ${e}"
}
try { new File('/var/jenkins_home/init.groovy.d/running-coach-db-url.groovy').delete() } catch (ignored) {}
