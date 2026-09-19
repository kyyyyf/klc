class Shape {
public:
    virtual double Area() const = 0;
};

void MakeLocalClass() {
    class LocalShape {
    public:
        virtual double Area() const = 0;
    };
}
