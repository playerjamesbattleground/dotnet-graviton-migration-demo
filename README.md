# About this repo
The purpose of this repo is to showcase the process of containerizing and deploying a .NET application on EKS Nodes powered by AWS Graviton processors.

## This repo has 3 directories:
1. CFN_Yaml: Contains cloudformation template to create the infrastructure needed for deploying the .NET application with Jenkins Pipeline.
2. Dotnet_App: Contains source code for the .NET application GadgetsOnline.
3. Jenkins_Config: Contains files required to configure Jenkins after installation.
4. K8s_Yaml: Contains kubernetes object yaml files which will be used to deploy the .NET application container image in EKS Cluster.

## Instruction to deploy the Cloudformation templates and .NET application 
### Pre-requisite
1. Install following utilities
    1. [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2-linux.html)
    2. [The Kubernetes CLI](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
    3. [Helm - the package manager for Kubernetes](https://helm.sh/docs/intro/install/)

    Configure the AWS CLI with an IAM user that has sufficient privileges to create an EKS cluster and other AWS resources required for this project. Verify that the CLI can authenticate properly by running aws sts get-caller-identity.

2. Set environment variables

    ```
    export CFN_STACK_NAME="GadgetsOnlineAppInfra"
    export AWS_DEFAULT_REGION="ap-south-1"
    export AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
    export AWS_CLI_PROFILE_NAME=default
    export TEMPDIR=$(mktemp)
    export KUBERNETES_VERSION=1.27
    export EKS_CLUSTER_NAME='GadgetsOnline'
    ```

    > **Warning**
    > If you open a new terminal/session to run steps in this procedure, you need to set some or all of the environment variables again. To remind yourself of these values, type:
    > `echo $AWS_DEFAULT_REGION $AWS_ACCOUNT_ID $AWS_CLI_PROFILE_NAME $TEMPDIR $KUBERNETES_VERSION $EKS_CLUSTER_NAME`

3. Create Required SSM Parameters using AWS CLI command (`aws ssm put-parameter --type SecureString --overwrite --name <Parameter_Name> --value <Parameter_Value>`). These parameters are used by the CloudFormation template and Jenkins configuration script. Not setting or misconfiguring these SSM Parameters will leads to failure in CloudFormation template deployment or failure in configuring Jenkins.
    1. [GitHub-Access-Token](https://docs.github.com/en/enterprise-server@3.4/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token)
        ```
        $ aws ssm put-parameter --type SecureString --overwrite --name GitHub-Access-Token --value <Parameter_Value>
        ```
    2. [GitRepo-Integration-Key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account)
        ```
        $ aws ssm put-parameter --type SecureString --overwrite --name GitRepo-Integration-Key --value "$(cat /location/of/the/github/private/key.pem)"
        ```
    3. IAM-Admin-Access-Key-ID
        ```
        $ aws ssm put-parameter --type SecureString --overwrite --name IAM-Admin-Access-Key-ID --value $(grep -A2 "${AWS_CLI_PROFILE_NAME}" ~/.aws/credentials | awk -F'=' '/aws_access_key_id/{print $NF}' | tr -d ' ')
        ```
    4. IAM-User-Secret-Access-Key
        ```
        $ aws ssm put-parameter --type SecureString --overwrite --name IAM-User-Secret-Access-Key --value $(grep -A2 "${AWS_CLI_PROFILE_NAME}" ~/.aws/credentials | awk -F'=' '/aws_secret_access_key/{print $NF}' | tr -d ' ')
        ```
    5. Jenkins-Password
        ```
        $ aws ssm put-parameter --type SecureString --overwrite --name Jenkins-Password --value "$(cat /dev/urandom | env LC_ALL=C tr -dc 'a-zA-Z0-9' | fold -w 16 | head -n 1)"
        ```

    > **Note**
    > Provide same Access Key and Secret Access Key you used to configure your AWS CLI above in the SSM parameters IAM-Admin-Access-Key-ID and IAM-User-Secret-Access-Key.

4. Clone this repo and upload all the directories and files except DotNet_App to a S3 bucket and then create following environment variable.
    ```
    $ export YAML_S3_BUCKET_URL='https://s3.amazonaws.com/<your_bucket_name>/<patch to the location where repo files are uploaded>'
    ```

    > **Note**
    > Replace <your_bucket_name> and <patch to the location where repo files are uploaded> with your S3 bucket name and path where repo files were uploaded.

### CFN Stack creation
5. Create CloudFormation (CFN) Stack using the main CloudFormation template.
    ```
    $ aws cloudformation create-stack --stack-name ${CFN_STACK_NAME} \
    --parameters ParameterKey=StackTemplateLocation,ParameterValue=${YAML_S3_BUCKET_URL} \
      ParameterKey=EKSKubernetesVersion,ParameterValue=${KUBERNETES_VERSION} \
    --template-url ${YAML_S3_BUCKET_URL}/CFN_Yaml/Main_CFN_Template.yaml \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND CAPABILITY_NAMED_IAM
    ```

    > **Note**
    > Stack creation can easily take 15 to 20 min, so please be patient.

### Creation of Jenkins CI/CD pipeline
6. Once the main CFN stack transitions to "CREATE_COMPLETE" state, use following command to get Jenkins master URL and credential.
    ```
    $ echo "Jenkins UI Username / Password : admin / $(aws ssm get-parameter --name Jenkins-Password --query 'Parameter.Value' --output text --with-decryption)"
    $ echo "Jenkins URL: $(aws cloudformation describe-stacks --stack-name $CFN_STACK_NAME --output json --query 'Stacks[*].Outputs[?OutputKey==`JenkinsURL`].OutputValue')"
    ```

7. Login to Jenkins UI using above URL and Credential.
8. Create a new Pipeline using following steps:

    1. Navigate to "Dashboard" and select "New Item"
    2. In "item name" field, provide a name (say: GadgetsOnlineAppPipeline) for the pipeline.
    3. Select "Pipeline" from the options displayed below the "item name" text box and then select "OK".
    4. Select the CheckBox for "GitHub project" and in "Project url" text box provide SSH URL of our GitHub Repo which is `git@github.com:santosh-at-github/dotnet_on_graviton.git`
    5. Under "Build Triggers" section, select "GitHub hook trigger for GITScm polling"
    6. In "Pipeline" drop-down, select "Pipeline script from SCM".
    7. In "SCM" drop-down, select "Git".
    8. In "Repository URL" text field, provide our GitHub Repo SSH URL `git@github.com:santosh-at-github/dotnet_on_graviton.git`
    9. In "Credentials" drop-down select the entry starting with "git". The Error should disappear after selecting the Credential.
    10. In "Branch Specifier" field, replace "master" with "main".
    11. Provide "Script Path" as "Jenkins_Config/Jenkinsfile" and click on "Save".
    12. Now in the pipeline menu, select "Build Now" to manually trigger the build.
    13. To trigger build automatically, provide Jankins WebHook URL in your GitHub Repo Setting as explained [here](https://www.blazemeter.com/blog/how-to-integrate-your-github-repository-to-your-jenkins-project).
        PayLoad URL should be in following format: `http://\<Jenkins_ELB_DNS\>/github-webhook/`\
        Content Type should be `application/json`.
    14. Once the WebHook PayLoad URL and application setting is saved, then Jenkins will be notified for all the commit which happens to this repo so that Jenkins can trigger the build-pipeline.
9. Once the Jenkins build pipeline completes successfully, it will deploy the GadgetsOnline application on our EKS Cluster as Deployment and a LoadBalancer Service.

### Exploring deployed .NET application
10. Let's setup the kubeconfig file so that we can use kubectl to inspect what's running inside the EKS Cluster. Execute below command to setup the kubeconfig file:
    ```
    $ aws eks update-kubeconfig --nam ${EKS_CLUSTER_NAME}
    ```
11. After this you can use kubectl commands to explore what's running inside the EKS cluster. Execute below command to show the deployment and service running inside the default namespace of the EKS cluster:
    ```
    $ kubectl get deployment,svc
    ```
12. Copy and paste the ELB URL present in "EXTERNAL-IP" field of the "gadgets-online-svc" service in your browser to access the application.

### To Do:
1. Install metrics server, setup HPA for the application.
17. Instruction to generate load and showcase that the application infra is elastic.
18. Instruction for cleanup
