using Xunit;

public class FooTests
{
    [Fact]
    public void DoFoo_Returns42()
    {
        Assert.Equal(42, Foo.DoFoo());
    }
}
