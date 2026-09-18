from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_customuser_must_change_password_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='participant',
            name='stopped_date',
            field=models.DateField(blank=True, null=True, help_text="Date participation was stopped (end of study or drop-out). Last date step data was captured."),
        ),
    ]