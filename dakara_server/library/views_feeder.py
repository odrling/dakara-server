from rest_framework import status
from rest_framework.generics import ListAPIView, CreateAPIView
from rest_framework.permissions import IsAuthenticated

from library import models
from library import serializers
from library import permissions


class FeederListView(ListAPIView):

    permission_classes = [IsAuthenticated, permissions.IsLibraryManager]
    queryset = models.Song.objects.all()
    serializer_class = serializers.SongOnlyFilePathSerializer
    pagination_class = None


class FeederView(CreateAPIView):
    permission_classes = [IsAuthenticated, permissions.IsLibraryManager]
    serializer_class = serializers.FeederSerializer

    def perform_create(self, serializer):
        # get the list serializer for added elements
        serializer_added = serializer.get_subserializer("added")

        # save the added elements
        serializer_added.save()

        # get the list of deleted elements
        list_deleted = serializer.validated_data["deleted"]

        # remove the deleted elements
        for song in list_deleted:
            models.Song.objects.get(**song).delete()

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)

        # replace returned status code by generic 200
        response.status_code = status.HTTP_200_OK

        return response

    #
    # def post(self, request, *args, **kwargs):
    #     serializer = self.serializer_class(request.data)
    #     if not serializer.is_valid():
    #
