locals {
  env = "dev"
}

module "network" {
  source  = "../../modules/network"
  project = var.project
  env     = local.env
  azs     = var.azs
}

module "security" {
  source            = "../../modules/security"
  project           = var.project
  env               = local.env
  vpc_id            = module.network.vpc_id
  anthropic_api_key = var.anthropic_api_key
  github_token      = var.github_token
}

module "messaging" {
  source  = "../../modules/messaging"
  project = var.project
  env     = local.env
}

module "data" {
  source  = "../../modules/data"
  project = var.project
  env     = local.env
}

module "ecs" {
  source  = "../../modules/ecs"
  project = var.project
  env     = local.env

  aws_region         = var.aws_region
  vpc_id             = module.network.vpc_id
  public_subnet_ids  = module.network.public_subnet_ids
  private_subnet_ids = module.network.private_subnet_ids

  alb_sg_id    = module.security.alb_sg_id
  api_sg_id    = module.security.api_sg_id
  worker_sg_id = module.security.worker_sg_id

  repos_table_name = module.data.repos_table_name
  repos_table_arn  = module.data.repos_table_arn
  jobs_table_name  = module.data.jobs_table_name
  jobs_table_arn   = module.data.jobs_table_arn

  queue_url = module.messaging.queue_url
  queue_arn = module.messaging.queue_arn

  anthropic_secret_arn    = module.security.anthropic_secret_arn
  github_token_secret_arn = module.security.github_token_secret_arn

  api_image    = var.api_image
  worker_image = var.worker_image
}

module "frontend" {
  source       = "../../modules/frontend"
  project      = var.project
  env          = local.env
  alb_dns_name = module.ecs.alb_dns_name
}

module "observability" {
  source  = "../../modules/observability"
  project = var.project
  env     = local.env

  cluster_name             = module.ecs.cluster_name
  api_service_name         = module.ecs.api_service_name
  worker_service_name      = module.ecs.worker_service_name
  queue_name               = module.messaging.queue_name
  alb_arn_suffix           = module.ecs.alb_arn_suffix
  target_group_arn_suffix  = module.ecs.target_group_arn_suffix
}
