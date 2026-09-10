#See https://aka.ms/containerfastmode to understand how Visual Studio uses this Dockerfile to build your images for faster debugging.

FROM mcr.microsoft.com/dotnet/aspnet:6.0 AS base
WORKDIR /app
EXPOSE 80

# Pin the compile stage to the build machine's own architecture. `dotnet publish`
# emits architecture-neutral IL, so there is nothing to gain from compiling under
# emulation for each target -- and a great deal of build time to lose. Only the
# runtime stage below is resolved per target architecture.
#
# This one keyword is what makes `--platform linux/amd64,linux/arm64` produce a
# multi-architecture image at full native build speed.
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:6.0 AS build
WORKDIR /src
COPY ["Dotnet_App/GadgetsOnline/GadgetsOnline.csproj", "GadgetsOnline/"]
RUN dotnet restore "GadgetsOnline/GadgetsOnline.csproj"
COPY ./Dotnet_App/ .
WORKDIR "/src/GadgetsOnline"
RUN dotnet build "GadgetsOnline.csproj" -c Release -o /app/build

FROM build AS publish
RUN dotnet publish "GadgetsOnline.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app/publish .
ENTRYPOINT ["dotnet", "GadgetsOnline.dll"]
