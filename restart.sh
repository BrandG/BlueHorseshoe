docker container prune -f
docker image rm docker-bluehorseshoe
docker image rm docker-mongo
cd /workspaces/BlueHorseshoe/docker/
docker-compose up --build