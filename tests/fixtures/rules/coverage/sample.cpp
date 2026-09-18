class Shape {
public:
    virtual double Area() const = 0;
};

class Circle : public Shape {
public:
    virtual double Area() const override;
};
