// AI Running Coach — Family Portal deploy pipeline (mirrors MyGarage/AudibleConverter).
// Jenkins runs on the Raspberry Pi, polls GitHub every ~3 min, then builds and
// (re)deploys the container. The container listens on 8090 internally; this app
// is published on host port 8095. The DATABASE_URL secret points at the shared
// PostgreSQL (192.168.1.129:5432) and is injected from Jenkins credentials.
pipeline {
    agent any
    options { disableConcurrentBuilds() }
    triggers { pollSCM('H/3 * * * *') }
    parameters {
        booleanParam(name: 'ENABLE_AI_COACHING', defaultValue: params.ENABLE_AI_COACHING ?: false,
                     description: 'Enable paid, manual OpenAI requests. Requires running-coach-openai-api-key Secret text.')
        string(name: 'COACH_OPENAI_MODEL', defaultValue: params.COACH_OPENAI_MODEL ?: 'gpt-5-mini',
               description: 'OpenAI model supporting Responses API Structured Outputs.')
    }

    environment {
        IMAGE     = 'ai-running-coach:latest'
        CONTAINER = 'ai-running-coach'
        HOST_PORT = '8095'
    }

    stages {
        stage('Build image') {
            steps { sh 'docker build -t $IMAGE .' }
        }

        stage('Deploy container') {
            steps {
                script {
                    def secrets = [string(credentialsId: 'running-coach-database-url', variable: 'DATABASE_URL')]
                    if (params.ENABLE_AI_COACHING) {
                        secrets.add(string(credentialsId: 'running-coach-openai-api-key', variable: 'OPENAI_API_KEY'))
                    }
                    withEnv(["OPENAI_API_KEY=", "OPENAI_MODEL=${params.COACH_OPENAI_MODEL ?: 'gpt-5-mini'}"]) {
                        withCredentials(secrets) {
                            sh '''
                                docker rm -f $CONTAINER 2>/dev/null || true
                                docker run -d \
                                    --name $CONTAINER \
                                    --restart unless-stopped \
                                    -p $HOST_PORT:8090 \
                                    -e DATABASE_URL \
                                    -e OPENAI_API_KEY \
                                    -e OPENAI_MODEL \
                                    -e COACH_AUTO_SEED=1 \
                                    $IMAGE
                            '''
                        }
                    }
                }
            }
        }

        stage('Health check') {
            steps {
                sh '''
                    sleep 8
                    docker exec $CONTAINER python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:8090/health', timeout=8); sys.exit(0 if r.status==200 else 1)"
                    echo "AI Running Coach OK su http://192.168.1.129:8095/"
                '''
            }
        }
    }

    post {
        success { echo 'Deploy AI Running Coach completato. UI: http://192.168.1.129:8095/' }
        failure { echo 'Deploy AI Running Coach FALLITO. Log: docker logs ai-running-coach' }
    }
}
