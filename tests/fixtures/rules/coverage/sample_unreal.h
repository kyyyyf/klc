UCLASS()
class AMyActor : public AActor
{
    GENERATED_BODY()

public:
    UFUNCTION(BlueprintCallable)
    void DoSomething();

    UPROPERTY(EditAnywhere)
    int32 Health;
};
